from http.server import BaseHTTPRequestHandler, HTTPServer
from time import sleep
from re import search, IGNORECASE
from os import environ

auth_token = None

def get_env_var(name):
    env_var = environ.get(name)

    if(not env_var):
        print(f'[{name}] environment variable not found!')
        exit(-1)
    return env_var

def check_auth(auth):
    global auth_token

    match = search('Bearer (?P<token>[^\s]+$)', auth, flags = IGNORECASE)

    if(not match):
        return False
    
    return auth_token == match.group('token')
    
def run_script(target):
    print(f"target {target}")
    pass

class HTTPHandler(BaseHTTPRequestHandler):
    server_version = ''
    sys_version = ''

    def do_POST(self):
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()

        if(check_auth(self.headers.get("Authorization", ""))):
            run_script(self.headers.get("Target", ""))

        self.wfile.write(bytes(" ", "utf8"))

def main():
    global auth_token
    auth_token = get_env_var('WEBHOOK_AUTH_TOKEN')
    port = int(get_env_var('WEBHOOK_PORT'))

    while True:
        try:
            with HTTPServer(('', port), HTTPHandler) as server:
                print(f'running on port [{port}]')
                server.serve_forever()
        except Exception as e:
            print(e)
            sleep(5)

if __name__ == '__main__':
    main()