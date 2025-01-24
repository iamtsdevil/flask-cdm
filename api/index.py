from flask import Flask, request, jsonify
import asyncio
from modules.downloader import drm_downloader, validate_keys, fetch_mpd, direct_downloads
from modules.logging import setup_logging
from modules.config import load_configurations
from modules.proxy import init_proxy, proxyscrape, allowed_countries, rotate_proxy, used_proxy, read_proxies_from_file
from modules.pssh import fetch_manifest, get_pssh_from_m3u8_url, extract_kid_and_pssh_from_mpd, kid_to_pssh
from modules.utils import banners, print_license_keys, clear_screen, parse_headers, extract_widevine_pssh, bypass_manifest_fetching, is_token_valid
from modules.license_retrieval import get_license_keys, configure_session, handle_learnyst_service

app = Flask(__name__)
logging = setup_logging()
config = load_configurations()

def setup_proxy(args):
    # Proxy setup logic, extracted directly from the main script
    proxies = []
    proxy_method = args.get("proxy", "").lower()
    country_code = args.get("country_code", "").upper()

    if proxy_method == "file":
        proxies = read_proxies_from_file('proxies.txt')
        if not proxies:
            logging.warning("No proxies found in the file.")
            return {}

    elif proxy_method == "scrape":
        if country_code in allowed_countries:
            logging.info(f"Using scrape proxy method for country: {country_code}.")
            proxy_url = proxyscrape(country_code)
            if proxy_url:
                proxies.append(proxy_url)
            else:
                logging.warning(f"No proxies found for country: {country_code}.")
        else:
            logging.info("Using 'scrape' proxy method with no specific country code.")
            proxy_url = proxyscrape()
            if proxy_url:
                proxies.append(proxy_url)
            else:
                logging.warning("No proxies found.")

    elif proxy_method == "rotate":
        logging.info("Using 'rotate' proxy method.")
        proxy = rotate_proxy()
        proxies.append(proxy)

    elif proxy_method.upper() in allowed_countries:
        logging.info(f"Using country-based proxy for: {proxy_method.upper()}.")
        proxy_data = init_proxy({"zone": proxy_method.upper(), "port": "peer"})
        proxies.append(proxy_data)

    else:
        if proxy_method:
            logging.info(f"Using provided proxy: {proxy_method}")
            proxy_url = proxy_method
            proxies.append(used_proxy(proxy_url) if proxy_url.startswith('socks') else used_proxy({'http': proxy_url, 'https': proxy_url}))

    working_proxies = {}
    for proxy in proxies:
        test_proxy = used_proxy(proxy)
        logging.info(f"Testing proxy: {test_proxy}")
        if not test_proxy:
            logging.warning(f"Invalid proxy format: {proxy}")
            continue
        
        session = configure_session(test_proxy)
        try:
            response = session.get('https://httpbin.org/ip', timeout=5)
            if response.status_code == 200:
                logging.info(f"Working proxy found: {test_proxy}")
                working_proxies = test_proxy
                break
        except Exception as e:
            logging.error("No working proxies found.")
            continue
            
    return working_proxies

@app.route('/')
def index():
    return jsonify({
        "message": "Welcome to the DRM Downloader Flask API!",
        "endpoints": {
            "/download": "Start a DRM-protected download",
            "/license-keys": "Fetch license keys",
            "/proxy": "Setup and test proxies"
        }
    })

@app.route('/proxy', methods=['POST'])
def proxy():
    args = request.json
    proxy = setup_proxy(args)
    if proxy:
        return jsonify({"status": "success", "proxy": proxy})
    return jsonify({"status": "error", "message": "No valid proxies found."})

@app.route('/license-keys', methods=['POST'])
def license_keys():
    args = request.json
    pssh = args.get('pssh')
    license_url = args.get('license_url')
    service = args.get('service')
    content_id = args.get('content_id')

    if not pssh or not license_url or not service:
        return jsonify({"status": "error", "message": "Missing required fields: pssh, license_url, or service."})
    
    proxy = setup_proxy(args)
    keys = get_license_keys(pssh, license_url, service, content_id, proxy)
    if keys:
        return jsonify({"status": "success", "keys": keys})
    return jsonify({"status": "error", "message": "Failed to fetch license keys."})

@app.route('/download', methods=['POST'])
def download():
    args = request.json
    manifest_url = args.get('manifest_url')
    output_name = args.get('output_name', 'default')
    proxy = setup_proxy(args)

    if not manifest_url:
        return jsonify({"status": "error", "message": "Manifest URL is required."})

    try:
        direct_downloads(manifest_url, output_name, proxy)
        return jsonify({"status": "success", "message": f"Download started for {output_name}."})
    except Exception as e:
        logging.error(f"Error during download: {e}")
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
