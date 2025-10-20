from http.server import BaseHTTPRequestHandler, HTTPServer
from time import sleep
from re import search, IGNORECASE
from os import environ, scandir
from subprocess import run
from os.path import join, realpath, dirname
import logging
from urllib.parse import parse_qs

log:logging.Logger
auth_token:str
scripts_path:str

def setup_logging():
    global log

    file_path = dirname(realpath(__file__))

    # Create custom formatter for YYYY-MM-DD HH:MM:SS:mmm format
    class CustomFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            from datetime import datetime
            dt = datetime.fromtimestamp(record.created)
            # Format: YYYY-MM-DD HH:MM:SS:mmm
            return dt.strftime('%Y-%m-%d %H:%M:%S') + f':{int(record.msecs):03d}'

    # Create file handler
    handler = logging.FileHandler(f"{file_path}/log.txt", mode='a')
    handler.setLevel(logging.DEBUG)

    # Create and set custom formatter
    formatter = CustomFormatter('%(asctime)s %(levelname)s %(message)s')
    handler.setFormatter(formatter)

    # Configure root logger
    log = logging.getLogger()
    log.setLevel(logging.DEBUG)
    log.addHandler(handler)

def get_env_var(name):
    env_var = environ.get(name)

    if(not env_var):
        log.fatal(f'[{name}] environment variable not found!')
        exit(-1)
    return env_var

def check_auth(auth):
    global auth_token

    match = search('Bearer (?P<token>[^\\s]+$)', auth, flags = IGNORECASE)

    if(not match):
        return False

    return auth_token == match.group('token')

def sanitize_env_vars(env_vars):
    """
    Sanitize environment variables to prevent security vulnerabilities.
    Returns a sanitized dictionary or raises an exception if validation fails.
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
            log.warning(f"Environment variable name too long: {key[:50]}...")
            continue

        # Check variable value length
        if len(str(value)) > MAX_VAR_VALUE_LENGTH:
            log.warning(f"Environment variable value too long for key: {key}")
            continue

        # Validate variable name format (uppercase, alphanumeric, underscores only)
        if not search(VALID_NAME_PATTERN, key, IGNORECASE):
            log.warning(f"Invalid environment variable name: {key}")
            continue

        # Block dangerous variables
        if key.upper() in BLOCKED_VARS:
            log.warning(f"Blocked dangerous environment variable: {key}")
            continue

        # Convert value to string and store
        sanitized[key] = str(value)

    return sanitized
    
def run_script(target, env_vars=None):
    # make sure folder exists in the scripts_path, don't blindly run whatever was passed
    found = False

    for entry in scandir(scripts_path):
        if(entry.is_dir() and entry.name == target):
            found = True
            break

    if(not found):
        raise Exception(f"target [{target}] not found")

    script_location = join(scripts_path, target)
    full_script_path = join(scripts_path, target, 'script.sh')

    # Prepare environment with custom variables
    env = environ.copy()
    if env_vars:
        # Sanitize environment variables before using them
        sanitized_vars = sanitize_env_vars(env_vars)
        env.update(sanitized_vars)
        log.debug(f"Using sanitized environment variables: {list(sanitized_vars.keys())}")

    completed = run([full_script_path], cwd=script_location, check=False, capture_output=True, env=env)

    output = completed.stdout.decode("utf-8")
    output += '\n\n'
    output += completed.stderr.decode("utf-8")

    log.info(f"target [{target}] output: \n{output}")

    return output

def get_target(request):
    return request.headers.get("Target", "")

def get_vars(request):
    content_length = int(request.headers.get('Content-Length', 0))
    post_body = request.rfile.read(content_length).decode('utf-8') if content_length > 0 else ''

    # Parse form data to extract environment variables
    env_vars = {}
    if post_body:
        # parse_qs returns a dict with lists as values, e.g. {'key': ['value']}
        form_data = parse_qs(post_body)
        # Extract first value from each list and convert to string
        env_vars = {k: str(v[0]) for k, v in form_data.items() if v}

    return env_vars

class HTTPHandler(BaseHTTPRequestHandler):
    server_version = ''
    sys_version = ''

    def do_POST(self):
        if(check_auth(self.headers.get("Authorization", ""))):
            try:
                # Get script target
                target = get_target(self)

                # Get form fields to pass as environment vars
                env_vars = get_vars(self)

                # Run script with environment variables
                output = run_script(target, env_vars=env_vars)

                self.send_response(200)
                self.send_header('Content-type','text/html')
                self.end_headers()
                self.wfile.write(bytes(output + '\n', "utf8"))

            except Exception as e:
                log.error(f"error running script: {e}")

                self.send_response(500)
                self.send_header('Content-type','text/html')
                self.end_headers()
                self.wfile.write(bytes("bad target\n", "utf8"))

        else:
            self.send_response(403)
            self.send_header('Content-type','text/html')
            self.end_headers()
            self.wfile.write(bytes("Unauthorized\n", "utf8"))

    def log_message(self, format, *args):
        pass

def main():
    global auth_token
    global scripts_path

    setup_logging()

    auth_token = get_env_var('WEBHOOK_AUTH_TOKEN')
    port = int(get_env_var('WEBHOOK_PORT'))
    scripts_path = get_env_var('SCRIPTS_PATH')

    while True:
        try:
            with HTTPServer(('', port), HTTPHandler) as server:
                log.debug(f'running on port [{port}]')
                server.serve_forever()
        except Exception as e:
            log.error(e)
            sleep(5)

if __name__ == '__main__':
    main()