import multiprocessing
import os

# Worker configuration for memory optimization on Render
# Use gthread worker class for better memory efficiency with I/O bound tasks
worker_class = 'gthread'

# Limit workers based on available memory (Render free tier: ~512MB)
# 2 workers with threads is more memory-efficient than 4 sync workers
workers = 2
threads = 2

# Worker lifecycle management to prevent memory leaks
# Restart workers after handling N requests
max_requests = 500
max_requests_jitter = 50

# Timeout settings
timeout = 120
keepalive = 5

# Graceful timeout for worker shutdown
graceful_timeout = 30

# Worker backlog
backlog = 2048

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Process naming
proc_name = 'school_lms'

# Bind address (will be overridden by Render's PORT env var)
bind = '0.0.0.0:8000'

# Preload app for memory sharing between workers
preload_app = True

# Worker temp directory
worker_tmp_dir = '/dev/shm'

# Enable stats for monitoring
statsd_host = None
