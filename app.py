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
    
    # Inject JavaScript to handle all outgoing requests
    script = soup.new_tag('script')
    script.string = """
    (function() {
        var originalFetch = window.fetch;
        var originalXHR = window.XMLHttpRequest.prototype.open;

        var currentOnionDomain = document.cookie.split('; ').find(row => row.startsWith('current_onion_domain=')).split('=')[1];

        function modifyUrl(url) {
            if (typeof url === 'string' && !url.startsWith('http://127.0.0.1:8080/')) {

                return 'http://127.0.0.1:8080/' + (url.startsWith('/') ? currentOnionDomain + url : currentOnionDomain + '/' + url);
            }
            return url;
        }

        window.fetch = function(input, init) {
            if (typeof input === 'string') {
                input = modifyUrl(input);
            } else if (input instanceof Request) {
                input = new Request(modifyUrl(input.url), input);
            }
            return originalFetch.apply(this, arguments);
        };

        window.XMLHttpRequest.prototype.open = function(method, url, async, user, password) {
            url = modifyUrl(url);

            return originalXHR.call(this, method, url, async, user, password);
        };
    })();
    """
    soup.body.append(script)



    return str(soup)
# All route definitions go here
@app.route('/')
def index():
    return "Hello, World!"

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

        # Retrieve the current .onion domain from the session or cookie
        onion_domain = request.cookies.get('current_onion_domain', '')
        
        # If the path doesn't start with the .onion domain, prepend it
        if not path.startswith(onion_domain):
            path = f"{onion_domain}/{path}"

        # Extract the .onion domain and subpath
        parts = path.split('/', 1)
        onion_domain = parts[0]
        subpath = parts[1] if len(parts) > 1 else ''

        url = f"http://{onion_domain}/{subpath}"
        app.logger.info(f"Attempting to access: {url}")

        headers = {key: value for (key, value) in request.headers if key != 'Host'}
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

        # Handle POST requests
        data = request.get_data()
        files = request.files

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

        # Handle streaming responses
        def generate():
            for chunk in resp.iter_content(chunk_size=4096):
                yield chunk

        response = Response(generate(), resp.status_code, headers)

        # Set the current .onion domain in a cookie
        response.set_cookie('current_onion_domain', onion_domain)
        
        return response

    except RequestException as e:
        app.logger.error(f"Request error: {str(e)}")
        return f"Error accessing {path}: {str(e)}", 500
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return f"Unexpected error: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
