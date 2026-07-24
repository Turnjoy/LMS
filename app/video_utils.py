import re
from urllib.parse import parse_qs, quote, urlparse


ALLOWED_VIDEO_HOSTS = {
    'youtube.com',
    'www.youtube.com',
    'youtu.be',
    'vimeo.com',
    'player.vimeo.com',
    'drive.google.com',
}


def normalize_embedded_video_url(raw_url):
    """Return a safe iframe URL for supported lesson video providers."""
    value = (raw_url or '').strip()
    if not value:
        return None

    parsed = urlparse(value if '://' in value else f'https://{value}')
    host = (parsed.netloc or '').lower()
    if host not in ALLOWED_VIDEO_HOSTS:
        return None

    if host in ('youtube.com', 'www.youtube.com'):
        if parsed.path.startswith('/embed/'):
            video_id = parsed.path.split('/embed/', 1)[1].split('/')[0]
        else:
            video_id = parse_qs(parsed.query).get('v', [''])[0]
        return f'https://www.youtube.com/embed/{quote(video_id)}' if video_id else None

    if host == 'youtu.be':
        video_id = parsed.path.strip('/').split('/')[0]
        return f'https://www.youtube.com/embed/{quote(video_id)}' if video_id else None

    if host in ('vimeo.com', 'player.vimeo.com'):
        match = re.search(r'(\d+)', parsed.path)
        return f'https://player.vimeo.com/video/{match.group(1)}' if match else None

    if host == 'drive.google.com':
        match = re.search(r'/file/d/([^/]+)', parsed.path)
        if match:
            return f'https://drive.google.com/file/d/{quote(match.group(1))}/preview'
        if parsed.path.startswith('/open'):
            file_id = parse_qs(parsed.query).get('id', [''])[0]
            return f'https://drive.google.com/file/d/{quote(file_id)}/preview' if file_id else None
        if '/preview' in parsed.path:
            return value

    return None
