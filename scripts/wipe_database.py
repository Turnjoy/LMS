#!/usr/bin/env python
"""Script to wipe all data from the database while preserving schema."""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app, db
from app.models import (
    AssignmentSubmission,
    CBTQuestion,
    CBTExam,
    Assignment,
    Attendance,
    Result,
    TeacherAssignment,
    StudentClass,
    StudentParent,
    Parent,
    SchoolSetupPreference,
    TenantAISetting,
    TenantPublicProfile,
    PaymentGatewaySetting,
    StudentSubjectRegistration,
    TenantSubject,
    ClassSubject,
    StudentTermRegistration,
    StudentTermAccess,
    FeeInstallmentMilestone,
    FeeInstallmentPlan,
    FeeCategory,
    PaymentTransaction,
    AdmissionApplication,
    User,
    Term,
    Subject,
    Class,
    Tenant,
)

def wipe_database():
    """Truncate all tables in the correct order to respect foreign key constraints."""
    app = create_app()
    
    with app.app_context():
        print("Starting database wipe...")
        
        # Ensure schema is up to date first
        print("Ensuring schema is up to date...")
        from app import _ensure_runtime_schema
        _ensure_runtime_schema()
        
        # Define tables in dependency order (children before parents)
        tables_to_wipe = [
            AssignmentSubmission,
            CBTQuestion,
            CBTExam,
            Assignment,
            Attendance,
            Result,
            TeacherAssignment,
            StudentClass,
            StudentParent,
            Parent,
            SchoolSetupPreference,
            TenantAISetting,
            TenantPublicProfile,
            PaymentGatewaySetting,
            StudentSubjectRegistration,
            TenantSubject,
            ClassSubject,
            StudentTermRegistration,
            StudentTermAccess,
            FeeInstallmentMilestone,
            FeeInstallmentPlan,
            FeeCategory,
            PaymentTransaction,
            AdmissionApplication,
            User,
            Term,
            Subject,
            Class,
            Tenant,
        ]
        
        total_deleted = 0
        for table in tables_to_wipe:
            count = table.query.count()
            if count > 0:
                table.query.delete()
                print(f"  Deleted {count} records from {table.__tablename__}")
                total_deleted += count
        
        db.session.commit()
        print(f"\nDatabase wipe complete. Total records deleted: {total_deleted}")
        print("Schema preserved. Ready for fresh start.")

if __name__ == '__main__':
    wipe_database()
