from flask import Flask, request, Response, stream_with_context, redirect, make_response
import requests
import logging
from requests.exceptions import RequestException
import urllib.parse
from bs4 import BeautifulSoup
import re

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# Tor proxy settings
tor_proxy = {
    'http': 'socks5h://127.0.0.1:9050',
    'https': 'socks5h://127.0.0.1:9050'
}

# Session storage
sessions = {}

def check_tor_connection():
    try:
        response = requests.get('https://check.torproject.org/', proxies=tor_proxy, timeout=10)
        return 'Congratulations. This browser is configured to use Tor.' in response.text
    except Exception as e:
        app.logger.error(f"Error checking Tor connection: {str(e)}")
        return False

def modify_html(content, base_url):
    soup = BeautifulSoup(content, 'html.parser')
    
    for tag in soup.find_all(['a', 'link', 'img', 'script', 'form']):
        for attr in ['href', 'src', 'action']:
            if tag.has_attr(attr):
                url = tag[attr]
                if url.startswith('data:'):
                    # Skip data URLs (base64 encoded images)
                    continue
                if not url.startswith(('http://', 'https://', '//')):
                    full_url = urllib.parse.urljoin(base_url, url)
                    tag[attr] = request.host_url + full_url.split('://', 1)[1]
    
    # Fix base64 images
    for img in soup.find_all('img', src=re.compile(r'^http://127\.0\.0\.1:8080/.*base64,')):
        src = img['src']
        img['src'] = re.sub(r'^http://127\.0\.0\.1:8080/.*base64,', 'data:image/png;base64,', src)
    
    return str(soup)

@app.route('/health')
def health_check():
    if check_tor_connection():
        return "Tor is working correctly", 200
    else:
        return "Tor is not working correctly", 500

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    try:
        if not check_tor_connection():
            return "Tor is not working correctly", 500

        # Extract the .onion domain from the path or use a default
        parts = path.split('/', 1)
        if parts[0].endswith('.onion'):
            onion_domain = parts[0]
            subpath = parts[1] if len(parts) > 1 else ''
        else:
            # Use a default .onion domain if not provided
            onion_domain = 'default_onion_domain.onion'  # Replace with your default .onion domain
            subpath = path

        url = f"http://{onion_domain}/{subpath}"
        app.logger.info(f"Attempting to access: {url}")

        headers = {key: value for (key, value) in request.headers if key != 'Host'}
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

        # Handle POST requests
        data = request.form if request.method == 'POST' else None
        files = request.files if request.method == 'POST' else None

        # Get or create session
        session_id = request.cookies.get('session_id')
        if session_id not in sessions:
            sessions[session_id] = requests.Session()
        session = sessions[session_id]

        resp = session.request(
            method=request.method,
            url=url,
            headers=headers,
            data=data,
            files=files,
            allow_redirects=False,
            proxies=tor_proxy,
            stream=True
        )

        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for (name, value) in resp.raw.headers.items()
                   if name.lower() not in excluded_headers]

        if resp.status_code in [301, 302, 303, 307, 308]:
            # Handle redirects
            location = resp.headers.get('Location')
            if location:
                if location.startswith('/'):
                    new_url = f"{request.host_url}{onion_domain}{location}"
                else:
                    new_url = f"{request.host_url}{onion_domain}/{location}"
                response = make_response(redirect(new_url, code=resp.status_code))
                for cookie in resp.cookies:
                    response.set_cookie(cookie.name, cookie.value, domain=request.host)
                return response

        content_type = resp.headers.get('Content-Type', '')
        if 'text/html' in content_type:
            content = modify_html(resp.content, url)
            response = make_response(content)
        else:
            response = Response(stream_with_context(resp.iter_content(chunk_size=10*1024)), 
                                resp.status_code, 
                                headers)

        # Set cookies from the response
        for cookie in resp.cookies:
            response.set_cookie(cookie.name, cookie.value, domain=request.host)

        response.status_code = resp.status_code
        response.headers.extend(headers)
        return response

    except RequestException as e:
        app.logger.error(f"Request error: {str(e)}")
        return f"Error accessing {path}: {str(e)}", 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return f"Unexpected error: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
