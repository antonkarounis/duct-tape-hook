from http.server import BaseHTTPRequestHandler, HTTPServer
from time import sleep
from re import search, IGNORECASE
from os import environ, scandir
from subprocess import run
from os.path import join, realpath, dirname
import logging

log = None
auth_token = None
scripts_path = None

def setup_logging():
    global log

    file_path = dirname(realpath(__file__))

    logging.basicConfig(filename=f"{file_path}/log.txt",
                        filemode='a',
                        format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                        datefmt='%H:%M:%S',
                        level=logging.DEBUG)

    log = logging.getLogger('dth')

def get_env_var(name):
    env_var = environ.get(name)

    if(not env_var):
        log.fatal(f'[{name}] environment variable not found!')
        exit(-1)
    return env_var

def check_auth(auth):
    global auth_token

    match = search('Bearer (?P<token>[^\s]+$)', auth, flags = IGNORECASE)

    if(not match):
        return False
    
    return auth_token == match.group('token')
    
def run_script(target):
    # make sure folder exists in the scripts_path, don't blindly run whatever was passed
    found = False

    for entry in scandir(scripts_path):
        if(entry.is_dir() and entry.name == target):
            found = True
            break

    if(not found):
        log.warn(f"target [{target}] not found")
        return False

    full_script_path = join(scripts_path, target, 'script.sh')
    output = run([full_script_path], check=True, capture_output=True).stdout.decode("utf-8")
    log.info(f"target [{target}] output: \n{output}")

    return True

class HTTPHandler(BaseHTTPRequestHandler):
    server_version = ''
    sys_version = ''

    def do_POST(self):
        if(check_auth(self.headers.get("Authorization", "")) and run_script(self.headers.get("Target", ""))):
            self.send_response(200)
            self.send_header('Content-type','text/html')
            self.end_headers()
            self.wfile.write(bytes("success", "utf8"))

        else:
            self.send_response(403)
            self.send_header('Content-type','text/html')
            self.end_headers()
            self.wfile.write(bytes("failure", "utf8"))

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