import json, sys, subprocess, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile
from os import symlink, unlink, listdir, rename, rmdir, chmod
from os.path import join, islink
import stat

#TODO - future improvements
# return any error messages to github - leverage fact that github shows responses to webhooks
# make github personal access token optional, for public repos it's not necessary
# use argparse?
# shift to unit tests and refactor code?

def load_args():
    if len(sys.argv) != 5:
        raise Exception("Required arguments missing [github_zip_url] [gitub_access_token] [output_path]")

    github_zip_url = sys.argv[1]
    github_access_token = sys.argv[2]
    output_path = sys.argv[3]
    script_path = sys.argv[4]

    return github_zip_url, github_access_token, output_path, script_path

def download_github_repo(github_zip_url, github_access_token, zipfile_path):
    headers = {
        'Authorization': f'token {github_access_token}',
        'Accept': 'application/vnd.github.v3+json'
    }

    request = urllib.request.Request(github_zip_url, headers=headers)
    
    with urllib.request.urlopen(request) as response:
        content = response.read()

        with open(zipfile_path, 'wb') as f:
            f.write(content)    

def shift_files_up(download_dir):
    repo_dir = join(download_dir, listdir(download_dir)[0])

    repo_files = listdir(repo_dir)

    for filename in repo_files:
        source = join(repo_dir, filename)
        target = join(download_dir, filename)

        rename(source, target)
    
    rmdir(repo_dir)

def execute_script(script_path):
    f = Path(script_path)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)

    proc = subprocess.Popen(
        script_path, 
        shell=True, 
        text=True, 
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        universal_newlines = True)
    
    print(f'script output below: \n{proc.stdout.read()}')

def deploy_repo():
    #grab required arguments from command line
    github_zip_url, github_access_token, output_path, script_relative_path = load_args()

    #set up files and paths
    timestamp = datetime.now().strftime('%y-%m-%d_%H:%M:%S')
    download_path = join(output_path, 'downloads', timestamp)  
    zipfile_path =  join(output_path, 'downloads', timestamp + '.zip')
    current_path = join(output_path, 'current')
    script_path = join(current_path, script_relative_path)

    #create new working directory
    print(f'creating new download path at {download_path}')
    Path(download_path).mkdir(parents=True, exist_ok=True)

    #grab the remote zip file from the url
    print(f'downloading to {zipfile_path}')
    download_github_repo(github_zip_url, github_access_token, zipfile_path)

    #unzip the file to the timestamped directory
    print(f'extracting zip to {download_path}')
    with ZipFile(zipfile_path, 'r') as zip:
        zip.extractall(download_path)

    #flatten the repo directory
    print(f'shifting files in {download_path}')
    shift_files_up(download_path)

    #unlink the previous 'current' dir if it exists
    if(islink(current_path)):
        print(f'unlinking {current_path}')
        unlink(current_path)

    #create a symlink to the current download
    print(f'symlinking between {download_path} -> {current_path}')
    symlink(download_path, current_path)

    print(f'executing script at {script_path}')
    execute_script(script_path)

class SimpleHTTPServer(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.headers.get('Content-Type') != 'application/json':
                self.send_response(500)
                print('github should be configured to send json, not urlencoded forms')

            event = self.headers.get('X-Github-Event')

            print(f'event={event}')

            if event == 'push':
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
            
                data = json.loads(post_data.decode())

                ref = data.get('ref')

                print(f'ref={ref}')

                if ref == 'refs/heads/main':
                    print('running deploy')

                    deploy_repo()
                else:
                    print('ignoring')

                self.send_response(200)
        except Exception as err:
            self.send_response(500)
            print(f'error caught {err}')

        finally:
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"thanks github!") 

if __name__ == '__main__':
    #check args exist...
    load_args()

    server_address = ('', 5000)
    http_server = HTTPServer(server_address, SimpleHTTPServer)
    http_server.serve_forever()
