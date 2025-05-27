import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import time
from functools import lru_cache
import logging

app = Flask(__name__)
CORS(app)

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO)

# Konfiguracja
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# Cache dla wyników (5 minut)
@lru_cache(maxsize=128)
def cached_search(query, cache_time):
    return perform_search(query)

def search_google(query):
    """
    Wyszukiwanie przez Google
    """
    results = []
    
    search_url = "https://www.google.com/search"
    search_query = f"site:pastebin.com {query}"
    params = {
        'q': search_query,
        'num': 20
    }
    
    try:
        response = requests.get(search_url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        # Debug
        logging.info(f"Google status: {response.status_code}")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Parsowanie wyników Google
        search_results = soup.find_all('div', class_='g')
        
        for idx, g in enumerate(search_results):
            link_elem = g.find('a')
            if link_elem and 'href' in link_elem.attrs:
                link = link_elem['href']
                
                if 'pastebin.com' in link and '/raw/' not in link and '/u/' not in link:
                    snippet = ""
                    
                    # Szukamy snippetu
                    snippet_selectors = [
                        ('span', {'class': 'aCOpRe'}),
                        ('div', {'class': 'IsZvec'}),
                        ('div', {'class': 'VwiC3b'}),
                        ('span', {'class': 'st'})
                    ]
                    
                    for tag, attrs in snippet_selectors:
                        snippet_elem = g.find(tag, attrs)
                        if snippet_elem:
                            snippet = snippet_elem.get_text(strip=True)
                            break
                    
                    if not snippet:
                        title_elem = g.find('h3')
                        if title_elem:
                            snippet = title_elem.get_text(strip=True)
                    
                    paste_id = link.split('/')[-1].split('?')[0]
                    
                    if paste_id and len(paste_id) == 8:
                        results.append({
                            'link': link,
                            'snippet': snippet[:200] + '...' if len(snippet) > 200 else snippet,
                            'paste_id': paste_id
                        })
        
        logging.info(f"Google znalazło {len(results)} wyników")
        
    except Exception as e:
        logging.error(f"Błąd Google: {str(e)}")
    
    return results

def search_pastebin_direct(query):
    """
    Przeszukuje bezpośrednio archiwum Pastebin i PUBLIC PASTES
    """
    results = []
    found_ids = set()  # Aby uniknąć duplikatów
    
    try:
        archive_url = "https://pastebin.com/archive"
        response = requests.get(archive_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Przeszukaj główną tabelę archiwum
        table = soup.find('table', class_='maintable')
        if table:
            rows = table.find_all('tr')[1:]  # Pomijamy nagłówek
            
            for row in rows[:20]:  # Sprawdzamy pierwsze 20 wpisów
                cells = row.find_all('td')
                if len(cells) >= 2:
                    link_elem = cells[0].find('a')
                    if link_elem:
                        paste_id = link_elem['href'].strip('/')
                        title = link_elem.text.strip()
                        
                        # Sprawdzamy tytuł lub pobieramy zawartość
                        if query.lower() in title.lower() or title.lower() == "untitled":
                            # Pobierz zawartość paste
                            try:
                                raw_url = f"https://pastebin.com/raw/{paste_id}"
                                raw_response = requests.get(raw_url, headers=HEADERS, timeout=3)
                                content = raw_response.text[:1000]  # Pierwsze 1000 znaków
                                
                                if query.lower() in content.lower():
                                    # Znajdź fragment z szukaną frazą
                                    idx = content.lower().find(query.lower())
                                    start = max(0, idx - 50)
                                    end = min(len(content), idx + 150)
                                    snippet = "..." + content[start:end].replace('\n', ' ') + "..."
                                    
                                    if paste_id not in found_ids:
                                        found_ids.add(paste_id)
                                        results.append({
                                            'link': f"https://pastebin.com/{paste_id}",
                                            'snippet': snippet,
                                            'paste_id': paste_id
                                        })
                            except:
                                # Jeśli nie można pobrać, użyj tytułu
                                if query.lower() in title.lower() and paste_id not in found_ids:
                                    found_ids.add(paste_id)
                                    results.append({
                                        'link': f"https://pastebin.com/{paste_id}",
                                        'snippet': title,
                                        'paste_id': paste_id
                                    })
        
        # 2. Przeszukaj sekcję "Public Pastes" (po prawej stronie)
        public_section = soup.find('div', class_='sidebar__title', string='Public Pastes')
        if public_section:
            # Znajdź kontener z publicznymi paste
            sidebar = public_section.find_parent('div')
            if sidebar:
                # Szukaj wszystkich linków w tej sekcji
                for item in sidebar.find_all('li'):
                    link = item.find('a')
                    if link and 'href' in link.attrs:
                        paste_id = link['href'].strip('/')
                        if len(paste_id) == 8 and paste_id not in found_ids:
                            # Pobierz tytuł i inne info
                            title_text = link.text.strip()
                            
                            # Sprawdź czy warto pobrać zawartość
                            if query.lower() in title_text.lower() or "untitled" in title_text.lower():
                                try:
                                    raw_url = f"https://pastebin.com/raw/{paste_id}"
                                    raw_response = requests.get(raw_url, headers=HEADERS, timeout=3)
                                    content = raw_response.text[:1000]
                                    
                                    if query.lower() in content.lower():
                                        idx = content.lower().find(query.lower())
                                        start = max(0, idx - 50)
                                        end = min(len(content), idx + 150)
                                        snippet = "..." + content[start:end].replace('\n', ' ') + "..."
                                        
                                        found_ids.add(paste_id)
                                        results.append({
                                            'link': f"https://pastebin.com/{paste_id}",
                                            'snippet': snippet,
                                            'paste_id': paste_id
                                        })
                                except:
                                    pass
        
        logging.info(f"Archiwum + Public Pastes: znaleziono {len(results)} wyników")
        
    except Exception as e:
        logging.error(f"Błąd archiwum: {str(e)}")
    
    return results

def search_duckduckgo(query):
    """
    Wyszukiwanie przez DuckDuckGo
    """
    results = []
    
    try:
        search_url = "https://html.duckduckgo.com/html/"
        params = {
            'q': f'site:pastebin.com {query}',
            's': '0',
            'dc': '0',
            'v': 'l',
            'o': 'json'
        }
        
        response = requests.post(search_url, data=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for result in soup.find_all('div', class_='result'):
            link_elem = result.find('a', class_='result__a')
            snippet_elem = result.find('a', class_='result__snippet')
            
            if link_elem and 'pastebin.com' in link_elem.get('href', ''):
                link = link_elem['href']
                paste_id = link.split('/')[-1].split('?')[0]
                
                snippet = snippet_elem.text if snippet_elem else link_elem.text
                
                if paste_id and len(paste_id) == 8:
                    results.append({
                        'link': link,
                        'snippet': snippet[:200] + '...' if len(snippet) > 200 else snippet,
                        'paste_id': paste_id
                    })
        
        logging.info(f"DuckDuckGo znalazło {len(results)} wyników")
        
    except Exception as e:
        logging.error(f"Błąd DuckDuckGo: {str(e)}")
    
    return results

def perform_search(query):
    """
    Główna funkcja wyszukiwania - próbuje różnych metod
    """
    # Najpierw próbuj Google
    results = search_google(query)
    
    # Jeśli brak wyników, próbuj DuckDuckGo
    if not results:
        logging.info("Próbuję DuckDuckGo...")
        results = search_duckduckgo(query)
    
    # Jeśli nadal brak, przeszukaj archiwum
    if not results:
        logging.info("Próbuję archiwum...")
        results = search_pastebin_direct(query)
    
    return results

@app.route('/search', methods=['GET'])
def search():
    """
    Endpoint API do wyszukiwania
    """
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({
            'error': 'Parametr q jest wymagany',
            'results': []
        }), 400
    
    logging.info(f"Otrzymano zapytanie: {query}")
    
    # Używamy cache
    cache_time = int(time.time() // 300)
    results = cached_search(query, cache_time)
    
    # Formatowanie odpowiedzi
    response_data = {
        'query': query,
        'count': len(results),
        'results': results
    }
    
    return jsonify(response_data)

@app.route('/health', methods=['GET'])
def health():
    """
    Health check endpoint
    """
    return jsonify({
        'status': 'ok', 
        'service': 'pastebin-search-api',
        'timestamp': int(time.time())
    })

@app.route('/debug', methods=['GET'])
def debug():
    """
    Debug endpoint - pokazuje co widzi scraper
    """
    try:
        response = requests.get("https://pastebin.com/archive", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        debug_info = {
            'status': 'ok',
            'archive_pastes': [],
            'public_pastes': []
        }
        
        # Archiwum
        table = soup.find('table', class_='maintable')
        if table:
            for i, row in enumerate(table.find_all('tr')[1:10]):  # Pierwsze 10
                cells = row.find_all('td')
                if len(cells) >= 2:
                    link = cells[0].find('a')
                    if link:
                        debug_info['archive_pastes'].append({
                            'title': link.text.strip(),
                            'id': link['href'].strip('/')
                        })
        
        # Public Pastes - różne możliwe selektory
        for selector in ['.sidebar__title', '.sidebar-title', 'h1']:
            public_title = soup.find(text='Public Pastes')
            if public_title:
                parent = public_title.find_parent()
                if parent:
                    next_element = parent.find_next_sibling()
                    if next_element:
                        for link in next_element.find_all('a', href=True)[:10]:
                            href = link['href']
                            if href.startswith('/') and len(href) == 9:
                                debug_info['public_pastes'].append({
                                    'title': link.text.strip(),
                                    'id': href.strip('/')
                                })
                        break
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/', methods=['GET'])
def index():
    """
    Główny endpoint z informacjami o API
    """
    return jsonify({
        'service': 'Pastebin Search API',
        'version': '1.0',
        'endpoints': {
            '/search?q=<query>': 'Wyszukuje pasty zawierające podaną frazę',
            '/health': 'Sprawdza status API',
            '/': 'Informacje o API'
        },
        'example': '/search?q=python%20code',
        'note': 'API używa wielu metod wyszukiwania: Google, DuckDuckGo i bezpośrednio archiwum Pastebin'
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)