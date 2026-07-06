from typing import List

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError, field_validator

from app import db
from app.decorators import role_required
from app.models import CBTExam, CBTQuestion

cbt_bp = Blueprint('cbt', __name__, url_prefix='/api/exams')


class QuizQuestionSchema(BaseModel):
    question_text: str = Field(description='The multiple-choice question context.')
    option_a: str = Field(description='Option A text')
    option_b: str = Field(description='Option B text')
    option_c: str = Field(description='Option C text')
    option_d: str = Field(description='Option D text')
    correct_option: str = Field(description="Must strictly be 'A', 'B', 'C', or 'D'")

    @field_validator('correct_option')
    @classmethod
    def validate_correct_option(cls, value):
        normalized = (value or '').strip().upper()
        if normalized not in {'A', 'B', 'C', 'D'}:
            raise ValueError("correct_option must strictly be 'A', 'B', 'C', or 'D'")
        return normalized

    @field_validator('question_text', 'option_a', 'option_b', 'option_c', 'option_d')
    @classmethod
    def validate_required_text(cls, value):
        cleaned = (value or '').strip()
        if not cleaned:
            raise ValueError('Question text and all options are required')
        return cleaned


class CBTQuizSchema(BaseModel):
    questions: List[QuizQuestionSchema]


def _build_generation_prompt(material_text, question_count):
    return f"""
You are an expert Nigerian secondary school CBT examiner.

Read the teacher-provided learning material and generate exactly {question_count}
multiple-choice questions for a school CBT exam.

Rules:
- Use only the supplied material as your source.
- Each question must have four options: A, B, C, and D.
- Only one option may be correct.
- correct_option must be exactly one of: A, B, C, D.
- Do not include explanations, markdown, numbering outside the schema, or extra keys.
- Return data matching the provided JSON schema.

Learning material:
{material_text}
""".strip()


def _get_genai_client():
    api_key = current_app.config.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError('GEMINI_API_KEY is not configured')

    return genai.Client(api_key=api_key)


def _generate_structured_quiz(material_text, question_count):
    model_name = current_app.config.get('GEMINI_MODEL') or 'gemini-1.5-flash'
    prompt = _build_generation_prompt(material_text, question_count)
    client = _get_genai_client()

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.35,
            response_mime_type='application/json',
            response_schema=CBTQuizSchema,
        ),
    )

    if getattr(response, 'parsed', None):
        return response.parsed

    if not getattr(response, 'text', None):
        raise ValueError('Gemini returned an empty response')

    return CBTQuizSchema.model_validate_json(response.text)


def _serialize_question(question):
    return {
        'id': question.id,
        'exam_id': question.exam_id,
        'question_text': question.question_text,
        'option_a': question.option_a,
        'option_b': question.option_b,
        'option_c': question.option_c,
        'option_d': question.option_d,
        'correct_option': question.correct_option,
    }


@cbt_bp.route('/generate-ai-questions', methods=['POST'])
@login_required
@role_required('local_admin', 'teacher')
def generate_ai_questions():
    data = request.get_json(silent=True) or {}
    exam_id = data.get('exam_id')
    material_text = (data.get('material_text') or data.get('context') or '').strip()

    try:
        question_count = int(data.get('question_count') or 10)
    except (TypeError, ValueError):
        return jsonify({'error': 'question_count must be a number'}), 400

    if not exam_id:
        return jsonify({'error': 'exam_id is required'}), 400

    if not material_text:
        return jsonify({'error': 'material_text is required'}), 400

    if question_count < 1 or question_count > 50:
        return jsonify({'error': 'question_count must be between 1 and 50'}), 400

    try:
        exam = CBTExam.query.filter_by(
            id=exam_id,
            tenant_id=current_user.tenant_id
        ).first()
        if not exam:
            return jsonify({'error': 'Exam not found for this tenant'}), 404

        quiz = _generate_structured_quiz(material_text, question_count)
        if not quiz.questions:
            return jsonify({'error': 'Gemini did not generate any questions'}), 502

        created_questions = []
        for generated_question in quiz.questions:
            question = CBTQuestion(
                tenant_id=current_user.tenant_id,
                exam_id=exam.id,
                question_text=generated_question.question_text,
                option_a=generated_question.option_a,
                option_b=generated_question.option_b,
                option_c=generated_question.option_c,
                option_d=generated_question.option_d,
                correct_option=generated_question.correct_option,
            )
            db.session.add(question)
            created_questions.append(question)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'AI questions generated and saved',
            'created_count': len(created_questions),
            'questions': [_serialize_question(question) for question in created_questions],
        }), 201
    except ValidationError as exc:
        db.session.rollback()
        return jsonify({
            'error': 'Generated questions failed schema validation',
            'details': exc.errors(),
        }), 502
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Unable to generate CBT questions')
        return jsonify({
            'error': 'Unable to generate CBT questions',
            'details': str(exc),
        }), 500
