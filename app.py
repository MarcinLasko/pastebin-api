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

def search_pastebin_direct(query, max_content_checks=10):
    """
    Przeszukuje archiwum - balansuje między szybkością a dokładnością
    
    Args:
        query: szukana fraza
        max_content_checks: ile paste'ów max pobrać (dla szybkości)
    """
    results = []
    found_ids = set()
    content_checks = 0
    
    try:
        archive_url = "https://pastebin.com/archive"
        response = requests.get(archive_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Znajdź wszystkie linki do paste'ów
        all_paste_links = []
        
        # Główna tabela archiwum
        table = soup.find('table', class_='maintable')
        if table:
            for row in table.find_all('tr')[1:]:
                link = row.find('a', href=True)
                if link:
                    all_paste_links.append({
                        'id': link['href'].strip('/'),
                        'title': link.text.strip()
                    })
        
        # Sidebar
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.startswith('/') and len(href) == 9 and href[1:].isalnum():
                paste_id = href.strip('/')
                if paste_id not in found_ids:
                    all_paste_links.append({
                        'id': paste_id,
                        'title': link.text.strip()
                    })
        
        logging.info(f"Znaleziono {len(all_paste_links)} paste'ów")
        
        # FAZA 1: Najpierw sprawdź wszystkie tytuły (szybkie)
        for paste in all_paste_links:
            if query.lower() in paste['title'].lower():
                found_ids.add(paste['id'])
                results.append({
                    'link': f"https://pastebin.com/{paste['id']}",
                    'snippet': f"[W tytule] {paste['title']}",
                    'paste_id': paste['id']
                })
        
        # FAZA 2: Sprawdź zawartość paste'ów z tytułem "Untitled" (wolniejsze)
        untitled_pastes = [p for p in all_paste_links 
                          if p['id'] not in found_ids 
                          and ('untitled' in p['title'].lower() or p['title'] == '')]
        
        for paste in untitled_pastes[:max_content_checks]:
            try:
                raw_url = f"https://pastebin.com/raw/{paste['id']}"
                raw_response = requests.get(raw_url, headers=HEADERS, timeout=2)
                
                if raw_response.status_code == 200:
                    content = raw_response.text[:2000]
                    
                    if query.lower() in content.lower():
                        # Znajdź fragment
                        idx = content.lower().find(query.lower())
                        start = max(0, idx - 80)
                        end = min(len(content), idx + 120)
                        snippet = content[start:end].replace('\n', ' ').strip()
                        if start > 0:
                            snippet = "..." + snippet
                        if end < len(content):
                            snippet = snippet + "..."
                        
                        found_ids.add(paste['id'])
                        results.append({
                            'link': f"https://pastebin.com/{paste['id']}",
                            'snippet': snippet,
                            'paste_id': paste['id']
                        })
                    
                    content_checks += 1
                    
            except Exception as e:
                logging.debug(f"Nie można pobrać {paste['id']}: {e}")
        
        # Sortuj - tytuły najpierw, potem zawartość
        results.sort(key=lambda x: 0 if '[W tytule]' in x['snippet'] else 1)
        
        logging.info(f"Znaleziono {len(results)} wyników (sprawdzono {content_checks} zawartości)")
        
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

def enrich_with_content(results, query, max_fetch=5):
    """
    Wzbogaca wyniki o rzeczywistą zawartość
    """
    enriched = []
    fetched = 0
    
    for result in results:
        # Jeśli snippet wygląda na domyślny, pobierz zawartość
        if "Pastebin.com is the number one" in result['snippet'] and fetched < max_fetch:
            try:
                raw_url = f"https://pastebin.com/raw/{result['paste_id']}"
                response = requests.get(raw_url, headers=HEADERS, timeout=3)
                if response.status_code == 200:
                    content = response.text[:2000]
                    
                    # Znajdź fragment z query
                    idx = content.lower().find(query.lower())
                    if idx != -1:
                        start = max(0, idx - 80)
                        end = min(len(content), idx + 120)
                        snippet = content[start:end].replace('\n', ' ').strip()
                        if start > 0:
                            snippet = "..." + snippet
                        if end < len(content):
                            snippet = snippet + "..."
                        
                        result['snippet'] = snippet
                        enriched.append(result)
                    fetched += 1
            except Exception as e:
                logging.debug(f"Nie można pobrać {result['paste_id']}: {e}")
        else:
            enriched.append(result)
    
    return enriched

def perform_search(query):
    """
    Główna funkcja wyszukiwania - priorytet na archiwum
    """
    # Zaczynamy od archiwum (najbardziej niezawodne)
    logging.info("Przeszukuję archiwum Pastebin...")
    results = search_pastebin_direct(query)
    
    # Jeśli mało wyników, spróbuj innych metod
    if len(results) < 5:
        # Próbuj DuckDuckGo (Google jest zbyt restrykcyjne)
        logging.info("Uzupełniam wyniki z DuckDuckGo...")
        ddg_results = search_duckduckgo(query)
        
        # Dodaj unikalne wyniki
        existing_ids = {r['paste_id'] for r in results}
        for r in ddg_results:
            if r['paste_id'] not in existing_ids:
                results.append(r)
    
    return results

@app.route('/search', methods=['GET'])
def search():
    """
    Endpoint API do wyszukiwania
    
    Parametry:
        q: szukana fraza (wymagane)
        mode: tryb wyszukiwania (opcjonalne)
            - 'balanced' (domyślny): sprawdza tytuły + 10 zawartości
            - 'fast': tylko tytuły (bardzo szybkie)
            - 'deep': sprawdza tytuły + 20 zawartości (wolniejsze)
    """
    query = request.args.get('q', '').strip()
    mode = request.args.get('mode', 'balanced')
    
    if not query:
        return jsonify({
            'error': 'Parametr q jest wymagany',
            'results': []
        }), 400
    
    logging.info(f"Otrzymano zapytanie: {query} (tryb: {mode})")
    
    # Ustaw limit sprawdzania zawartości w zależności od trybu
    content_limit = {
        'fast': 0,      # Tylko tytuły
        'balanced': 10, # Domyślnie 10 paste'ów
        'deep': 20      # Maksymalnie 20 paste'ów
    }.get(mode, 10)
    
    # Używamy cache
    cache_time = int(time.time() // 300)
    cache_key = f"{query}:{mode}:{cache_time}"
    
    # Modyfikuj funkcję perform_search aby przekazać limit
    results = search_pastebin_direct(query, max_content_checks=content_limit)
    
    # Formatowanie odpowiedzi
    response_data = {
        'query': query,
        'mode': mode,
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
    # Dla developmentu lokalnego
    app.run(host='0.0.0.0', port=5000, debug=True)