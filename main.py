"""
DuctTapeHook - A lightweight webhook utility that runs user-defined scripts.

This module provides an HTTP server that executes shell scripts in response to
authenticated webhook requests.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from time import sleep, time
from re import search, IGNORECASE
from os import environ, scandir, chmod
from subprocess import run, TimeoutExpired
from os.path import join, realpath, dirname, isdir
import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs
import secrets
import signal
import sys

# Constants
DEFAULT_PORT = 2000
MAX_CONTENT_LENGTH = 1_048_576  # 1MB
SCRIPT_TIMEOUT = 300  # 5 minutes
RETRY_DELAY = 5  # seconds
LOG_MAX_BYTES = 10_485_760  # 10MB
LOG_BACKUP_COUNT = 5
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_ATTEMPTS = 10


class Config:
    """Application configuration container."""

    def __init__(self):
        """Initialize configuration from environment variables."""
        self.log = None
        self.auth_token = None
        self.scripts_path = None
        self.port = DEFAULT_PORT


class RateLimiter:
    """Simple in-memory rate limiter for failed authentication attempts."""

    def __init__(self, max_attempts=RATE_LIMIT_MAX_ATTEMPTS, window=RATE_LIMIT_WINDOW):
        """
        Initialize rate limiter.

        Args:
            max_attempts: Maximum failed attempts allowed within window
            window: Time window in seconds
        """
        self.max_attempts = max_attempts
        self.window = window
        self.attempts = {}  # {ip: [timestamp1, timestamp2, ...]}

    def is_rate_limited(self, ip):
        """
        Check if an IP address is rate limited.

        Args:
            ip: IP address to check

        Returns:
            bool: True if rate limited, False otherwise
        """
        now = time()

        if ip not in self.attempts:
            return False

        # Remove old attempts outside the window
        self.attempts[ip] = [t for t in self.attempts[ip] if now - t < self.window]

        # Check if over limit
        return len(self.attempts[ip]) >= self.max_attempts

    def record_attempt(self, ip):
        """
        Record a failed authentication attempt.

        Args:
            ip: IP address that failed authentication
        """
        now = time()

        if ip not in self.attempts:
            self.attempts[ip] = []

        self.attempts[ip].append(now)


def setup_logging(config):
    """
    Configure logging with rotation and proper permissions.

    Args:
        config: Config object to store logger
    """
    file_path = dirname(realpath(__file__))
    log_file = join(file_path, "log.txt")

    class CustomFormatter(logging.Formatter):
        """Custom formatter for YYYY-MM-DD HH:MM:SS:mmm format."""

        def formatTime(self, record, datefmt=None):
            """Format timestamp with milliseconds."""
            from datetime import datetime
            dt = datetime.fromtimestamp(record.created)
            return dt.strftime('%Y-%m-%d %H:%M:%S') + f':{int(record.msecs):03d}'

    # Create rotating file handler
    handler = RotatingFileHandler(
        log_file,
        mode='a',
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT
    )
    handler.setLevel(logging.DEBUG)

    # Set restrictive permissions on log file
    try:
        chmod(log_file, 0o600)
    except FileNotFoundError:
        pass  # File doesn't exist yet, will be created by handler

    # Create and set custom formatter
    formatter = CustomFormatter('%(asctime)s %(levelname)s %(message)s')
    handler.setFormatter(formatter)

    # Configure root logger
    log = logging.getLogger()
    log.setLevel(logging.DEBUG)
    log.addHandler(handler)

    config.log = log


def get_env_var(config, name):
    """
    Get required environment variable or exit with error.

    Args:
        config: Config object with logger
        name: Environment variable name

    Returns:
        str: Environment variable value
    """
    env_var = environ.get(name)

    if not env_var:
        config.log.fatal(f'[{name}] environment variable not found!')
        sys.exit(1)

    return env_var


def check_auth(config, auth):
    """
    Validate bearer token using constant-time comparison.

    Args:
        config: Config object with auth_token
        auth: Authorization header value

    Returns:
        bool: True if authentication succeeds, False otherwise
    """
    match = search(r'Bearer (?P<token>[^\s]+$)', auth, flags=IGNORECASE)

    if not match:
        return False

    # Use constant-time comparison to prevent timing attacks
    return secrets.compare_digest(config.auth_token, match.group('token'))


def sanitize_env_vars(config, env_vars):
    """
    Sanitize environment variables to prevent security vulnerabilities.

    Args:
        config: Config object with logger
        env_vars: Dictionary of environment variables to sanitize

    Returns:
        dict: Sanitized environment variables

    Raises:
        ValueError: If too many variables provided
    """
    if not env_vars:
        return {}

    # Dangerous environment variables that should never be overridden
    BLOCKED_VARS = {
        'PATH', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH',
        'HOME', 'USER', 'LOGNAME', 'SHELL', 'IFS',
        'ENV', 'BASH_ENV', 'SHELLOPTS', 'PS4',
        'WEBHOOK_AUTH_TOKEN', 'WEBHOOK_PORT', 'SCRIPTS_PATH'
    }

    # Only allow alphanumeric variable names with underscores (standard env var naming)
    VALID_NAME_PATTERN = r'^[A-Z_][A-Z0-9_]*$'

    # Maximum lengths to prevent DoS
    MAX_VAR_NAME_LENGTH = 128
    MAX_VAR_VALUE_LENGTH = 4096
    MAX_VARS_COUNT = 50

    if len(env_vars) > MAX_VARS_COUNT:
        raise ValueError(f"Too many environment variables (max {MAX_VARS_COUNT})")

    sanitized = {}

    for key, value in env_vars.items():
        # Check variable name length
        if len(key) > MAX_VAR_NAME_LENGTH:
            config.log.warning(f"Environment variable name too long: {key[:50]}...")
            continue

        # Check variable value length
        if len(str(value)) > MAX_VAR_VALUE_LENGTH:
            config.log.warning(f"Environment variable value too long for key: {key}")
            continue

        # Validate variable name format (uppercase, alphanumeric, underscores only)
        if not search(VALID_NAME_PATTERN, key, IGNORECASE):
            config.log.warning(f"Invalid environment variable name: {key}")
            continue

        # Block dangerous variables
        if key.upper() in BLOCKED_VARS:
            config.log.warning(f"Blocked dangerous environment variable: {key}")
            continue

        # Convert value to string and store
        sanitized[key] = str(value)

    return sanitized


def run_script(config, target, env_vars=None):
    """
    Execute a script from the scripts directory.

    Args:
        config: Config object with logger and scripts_path
        target: Script directory name
        env_vars: Optional environment variables to pass to script

    Returns:
        str: Combined stdout and stderr output

    Raises:
        FileNotFoundError: If target directory not found
        TimeoutExpired: If script execution exceeds timeout
    """
    # Make sure folder exists in the scripts_path, don't blindly run whatever was passed
    found = False

    for entry in scandir(config.scripts_path):
        if entry.is_dir() and entry.name == target:
            found = True
            break

    if not found:
        raise FileNotFoundError(f"Target [{target}] not found")

    script_location = join(config.scripts_path, target)
    full_script_path = join(config.scripts_path, target, 'script.sh')

    # Prepare environment with custom variables
    env = environ.copy()
    if env_vars:
        # Sanitize environment variables before using them
        sanitized_vars = sanitize_env_vars(config, env_vars)
        env.update(sanitized_vars)
        config.log.debug(f"Using sanitized environment variables: {list(sanitized_vars.keys())}")

    # Run script with timeout
    completed = run(
        [full_script_path],
        cwd=script_location,
        check=False,
        capture_output=True,
        env=env,
        timeout=SCRIPT_TIMEOUT
    )

    output = completed.stdout.decode("utf-8")
    output += '\n\n'
    output += completed.stderr.decode("utf-8")

    config.log.info(f"Target [{target}] completed with return code {completed.returncode}")
    config.log.debug(f"Target [{target}] output: \n{output}")

    return output


def get_target(request):
    """
    Extract target header from request.

    Args:
        request: HTTP request object

    Returns:
        str: Target directory name
    """
    return request.headers.get("Target", "")


def get_vars(request):
    """
    Extract POST body parameters as environment variables.

    Args:
        request: HTTP request object

    Returns:
        dict: Environment variables from POST body

    Raises:
        ValueError: If Content-Length exceeds maximum
    """
    content_length = int(request.headers.get('Content-Length', 0))

    if content_length > MAX_CONTENT_LENGTH:
        raise ValueError(f"Request too large (max {MAX_CONTENT_LENGTH} bytes)")

    post_body = request.rfile.read(content_length).decode('utf-8') if content_length > 0 else ''

    # Parse form data to extract environment variables
    env_vars = {}
    if post_body:
        # parse_qs returns a dict with lists as values, e.g. {'key': ['value']}
        form_data = parse_qs(post_body)
        # Extract first value from each list (already a string, no need for str())
        env_vars = {k: v[0] for k, v in form_data.items() if v}

    return env_vars


class HTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for webhook endpoints."""

    server_version = ''
    sys_version = ''

    def do_GET(self):
        """Handle GET requests - health check endpoint."""
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK\n")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Not Found\n")

    def do_POST(self):
        """Handle POST requests - webhook execution."""
        client_ip = self.client_address[0]
        config = self.server.config
        rate_limiter = self.server.rate_limiter

        # Check rate limiting first
        if rate_limiter.is_rate_limited(client_ip):
            config.log.warning(f"Rate limit exceeded for IP: {client_ip}")
            self.send_response(429)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Too Many Requests\n")
            return

        # Check authentication
        auth_header = self.headers.get("Authorization", "")
        if not check_auth(config, auth_header):
            rate_limiter.record_attempt(client_ip)
            config.log.warning(f"Unauthorized request from {client_ip}")
            self.send_response(403)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Unauthorized\n")
            return

        # Authentication successful
        try:
            # Get script target
            target = get_target(self)
            config.log.info(f"Request from {client_ip} for target: {target}")

            # Get form fields to pass as environment vars
            env_vars = get_vars(self)

            # Run script with environment variables
            output = run_script(config, target, env_vars=env_vars)

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(bytes(output + '\n', "utf8"))

        except FileNotFoundError as e:
            config.log.error(f"Target not found: {e}")
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Target not found\n")

        except ValueError as e:
            config.log.error(f"Invalid request: {e}")
            self.send_response(400)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(bytes(f"Bad Request: {e}\n", "utf8"))

        except TimeoutExpired:
            config.log.error(f"Script timeout for target: {target}")
            self.send_response(504)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Script execution timeout\n")

        except Exception as e:
            config.log.error(f"Error executing script: {e}", exc_info=True)
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Internal Server Error\n")

    def log_message(self, format, *args):
        """Suppress default request logging (we use custom logging)."""
        pass


def signal_handler(signum, frame):
    """
    Handle shutdown signals gracefully.

    Args:
        signum: Signal number
        frame: Current stack frame
    """
    signal_name = signal.Signals(signum).name
    logging.info(f"Received {signal_name}, shutting down gracefully...")
    sys.exit(0)


def main():
    """Main entry point for the webhook server."""
    config = Config()

    setup_logging(config)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Load configuration from environment
    config.auth_token = get_env_var(config, 'WEBHOOK_AUTH_TOKEN')
    config.port = int(get_env_var(config, 'WEBHOOK_PORT'))
    config.scripts_path = get_env_var(config, 'SCRIPTS_PATH')

    # Validate scripts path exists
    if not isdir(config.scripts_path):
        config.log.fatal(f'SCRIPTS_PATH [{config.scripts_path}] is not a valid directory')
        sys.exit(1)

    # Create rate limiter
    rate_limiter = RateLimiter()

    config.log.info(f'Starting server on port {config.port}')
    config.log.info(f'Scripts path: {config.scripts_path}')

    retry_count = 0
    max_retries = 3

    while retry_count <= max_retries:
        try:
            with HTTPServer(('', config.port), HTTPHandler) as server:
                # Attach config and rate limiter to server
                server.config = config
                server.rate_limiter = rate_limiter

                config.log.info(f'Server running on port {config.port}')
                server.serve_forever()

        except KeyboardInterrupt:
            config.log.info("Received keyboard interrupt, shutting down...")
            break

        except OSError as e:
            # Fatal errors like port in use or permission denied
            config.log.fatal(f"Fatal error starting server: {e}")
            sys.exit(1)

        except Exception as e:
            retry_count += 1
            config.log.error(f"Server error (attempt {retry_count}/{max_retries}): {e}", exc_info=True)

            if retry_count > max_retries:
                config.log.fatal("Max retries exceeded, exiting")
                sys.exit(1)

            config.log.info(f"Retrying in {RETRY_DELAY} seconds...")
            sleep(RETRY_DELAY)

    config.log.info("Server shutdown complete")


if __name__ == '__main__':
    main()
