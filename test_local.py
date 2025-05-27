import requests
import time
import json

# Lokalny URL
API_URL = "http://127.0.0.1:5000"

# 32 różne frazy do testowania
test_queries = [
    "python", "javascript", "password", "api key", "config",
    "database", "mysql", "mongodb", "tutorial", "hack",
    "exploit", "vulnerability", "security", "bitcoin", "wallet",
    "email", "gmail", "credentials", "token", "secret",
    "php", "java", "c++", "golang", "rust",
    "docker", "kubernetes", "aws", "azure", "linux",
    "windows", "powershell"
]

def test_api():
    print(f"Testuję lokalne API: {API_URL}")
    print("=" * 50)
    
    # Najpierw sprawdź czy API działa
    try:
        health = requests.get(f"{API_URL}/health", timeout=5)
        if health.status_code == 200:
            print("✓ API działa poprawnie!")
        else:
            print("✗ API nie odpowiada poprawnie")
            return
    except:
        print("✗ Nie mogę połączyć się z API. Upewnij się że aplikacja działa!")
        return
    
    print("\nRozpoczynam test 32 zapytań...")
    print("=" * 50)
    
    successful = 0
    failed = 0
    total_results = 0
    
    for i, query in enumerate(test_queries, 1):
        try:
            print(f"\n[{i}/32] Testuję zapytanie: '{query}'")
            
            start_time = time.time()
            response = requests.get(f"{API_URL}/search", params={'q': query}, timeout=30)
            end_time = time.time()
            
            if response.status_code == 200:
                data = response.json()
                result_count = data['count']
                print(f"✓ Sukces! Znaleziono wyników: {result_count}")
                print(f"  Czas odpowiedzi: {end_time - start_time:.2f}s")
                
                if data['results']:
                    print(f"  Przykładowy wynik: {data['results'][0]['link']}")
                    print(f"  Snippet: {data['results'][0]['snippet'][:100]}...")
                
                successful += 1
                total_results += result_count
            else:
                print(f"✗ Błąd! Status: {response.status_code}")
                print(f"  Odpowiedź: {response.text}")
                failed += 1
                
        except Exception as e:
            print(f"✗ Błąd podczas zapytania: {str(e)}")
            failed += 1
        
        # Czekamy 2 sekundy przed następnym zapytaniem
        if i < 32:
            print("  Czekam 2 sekundy...")
            time.sleep(2)
    
    print("\n" + "=" * 50)
    print(f"PODSUMOWANIE TESTU:")
    print(f"Sukces: {successful}/32")
    print(f"Błędy: {failed}/32")
    print(f"Procent sukcesu: {(successful/32)*100:.1f}%")
    print(f"Łącznie znalezionych wyników: {total_results}")
    print(f"Średnia wyników na zapytanie: {total_results/successful if successful > 0 else 0:.1f}")

if __name__ == "__main__":
    test_api()