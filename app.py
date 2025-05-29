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
    found_ids = set()  # Dodajemy kontrolę duplikatów też tutaj
    
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
                    paste_id = link.split('/')[-1].split('?')[0]
                    
                    # WAŻNE: Sprawdź czy już nie mamy tego ID
                    if paste_id and len(paste_id) == 8 and paste_id not in found_ids:
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
                        
                        found_ids.add(paste_id)  # Oznacz jako znalezione
                        results.append({
                            'link': link,
                            'snippet': snippet[:200] + '...' if len(snippet) > 200 else snippet,
                            'paste_id': paste_id
                        })
        
        logging.info(f"Google znalazło {len(results)} unikalnych wyników")
        
    except Exception as e:
        logging.error(f"Błąd Google: {str(e)}")
    
    return results

def search_pastebin_direct(query, max_content_checks=10):
    """
    Przeszukuje archiwum - zawsze sprawdza zawartość
    
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
                    paste_id = link['href'].strip('/')
                    if paste_id not in found_ids:
                        all_paste_links.append({
                            'id': paste_id,
                            'title': link.text.strip()
                        })
                        found_ids.add(paste_id)
        
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
                    found_ids.add(paste_id)
        
        logging.info(f"Znaleziono {len(all_paste_links)} paste'ów do sprawdzenia")
        
        # Resetuj found_ids dla właściwego wyszukiwania
        found_ids = set()
        
        # Sprawdzaj zawartość WSZYSTKICH paste'ów (do limitu)
        for paste in all_paste_links[:max_content_checks]:
            try:
                raw_url = f"https://pastebin.com/raw/{paste['id']}"
                raw_response = requests.get(raw_url, headers=HEADERS, timeout=3)
                
                if raw_response.status_code == 200:
                    content = raw_response.text[:5000]  # Sprawdzamy więcej tekstu
                    
                    if query.lower() in content.lower():
                        # Znajdź najlepszy fragment
                        content_lower = content.lower()
                        idx = content_lower.find(query.lower())
                        
                        # Pokaż więcej kontekstu
                        start = max(0, idx - 100)
                        end = min(len(content), idx + 150)
                        snippet = content[start:end].replace('\n', ' ').replace('\r', '').strip()
                        
                        # Dodaj elipsy
                        if start > 0:
                            snippet = "..." + snippet
                        if end < len(content):
                            snippet = snippet + "..."
                        
                        results.append({
                            'link': f"https://pastebin.com/{paste['id']}",
                            'snippet': snippet,
                            'paste_id': paste['id'],
                            'title': paste['title']  # Dodajemy też tytuł dla kontekstu
                        })
                        
                        logging.debug(f"Znaleziono '{query}' w paste {paste['id']}")
                    
                content_checks += 1
                    
            except Exception as e:
                logging.debug(f"Nie można pobrać {paste['id']}: {e}")
        
        # Jeśli sprawdziliśmy limit ale są jeszcze paste'y, sprawdź przynajmniej tytuły pozostałych
        if content_checks >= max_content_checks:
            for paste in all_paste_links[max_content_checks:]:
                if query.lower() in paste['title'].lower():
                    results.append({
                        'link': f"https://pastebin.com/{paste['id']}",
                        'snippet': f"[Tylko tytul - nie sprawdzono zawartosci] {paste['title']}",
                        'paste_id': paste['id'],
                        'title': paste['title']
                    })
        
        logging.info(f"Znaleziono {len(results)} wyników (sprawdzono zawartość {content_checks} paste'ów)")
        
    except Exception as e:
        logging.error(f"Błąd archiwum: {str(e)}")
    
    return results

def search_duckduckgo(query):
    """
    Wyszukiwanie przez DuckDuckGo
    """
    results = []
    found_ids = set()  # Kontrola duplikatów
    
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
                
                # Sprawdź duplikaty
                if paste_id and len(paste_id) == 8 and paste_id not in found_ids:
                    found_ids.add(paste_id)
                    results.append({
                        'link': link,
                        'snippet': snippet[:200] + '...' if len(snippet) > 200 else snippet,
                        'paste_id': paste_id
                    })
        
        logging.info(f"DuckDuckGo znalazło {len(results)} unikalnych wyników")
        
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
    all_results = []
    seen_ids = set()
    
    # 1. Zaczynamy od archiwum (najbardziej niezawodne)
    logging.info("Przeszukuję archiwum Pastebin...")
    archive_results = search_pastebin_direct(query)
    
    # Dodaj tylko unikalne
    for r in archive_results:
        if r['paste_id'] not in seen_ids:
            seen_ids.add(r['paste_id'])
            all_results.append(r)
    
    # 2. Jeśli mało wyników, spróbuj innych metod
    if len(all_results) < 5:
        # Próbuj Google
        logging.info("Uzupełniam wyniki z Google...")
        google_results = search_google(query)
        
        for r in google_results:
            if r['paste_id'] not in seen_ids:
                seen_ids.add(r['paste_id'])
                all_results.append(r)
        
        # Jeśli nadal mało, próbuj DuckDuckGo
        if len(all_results) < 5:
            logging.info("Uzupełniam wyniki z DuckDuckGo...")
            ddg_results = search_duckduckgo(query)
            
            for r in ddg_results:
                if r['paste_id'] not in seen_ids:
                    seen_ids.add(r['paste_id'])
                    all_results.append(r)
    
    # 3. Wzbogać wyniki z domyślnymi snippetami
    enriched_results = enrich_with_content(all_results, query)
    
    logging.info(f"Zwracam {len(enriched_results)} unikalnych wyników")
    return enriched_results

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
    
    # Dodatowa deduplicacja na wszelki wypadek
    unique_results = []
    seen_ids = set()
    
    for r in results:
        if r['paste_id'] not in seen_ids:
            seen_ids.add(r['paste_id'])
            unique_results.append(r)
    
    # Formatowanie odpowiedzi
    response_data = {
        'query': query,
        'count': len(unique_results),
        'results': unique_results
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
    app.run(host='127.0.0.1', port=5000, debug=True)