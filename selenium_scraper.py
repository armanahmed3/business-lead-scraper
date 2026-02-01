"""
Selenium-based web scraper for business leads with email extraction.

UPDATED NOVEMBER 2025 - Working selectors for current Google Maps.
"""

import time
import random
import logging
import sys
import platform
try:
    import winreg
except ImportError:
    winreg = None
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from urllib.parse import quote_plus
import re

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException
)
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
import subprocess
import os

from robots_checker import RobotsChecker
from utils import sleep_random


def is_chrome_available():
    """Check if Chrome/Chromium is available on the system."""
    
    try:
        system = platform.system()
        
        if system == "Windows":
            # Check Windows registry or common installation paths
            if winreg is not None:
                try:
                    # Try to find Chrome in registry
                    reg_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
                        install_path = winreg.QueryValue(key, "")
                        if install_path and os.path.exists(install_path):
                            return True
                except:
                    pass
                
            # Check common installation paths
            common_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
            ]
            
            for path in common_paths:
                if os.path.exists(path):
                    return True
                    
        elif system == "Darwin":  # macOS
            # Check if Chrome is installed
            result = subprocess.run(['which', 'google-chrome'], 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    timeout=5)
            if result.returncode == 0:
                return True
                                    
        else:  # Linux and other Unix-like systems
            # Check if chrome/chromium is available
            result = subprocess.run(['which', 'google-chrome'], 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    timeout=5)
            if result.returncode == 0:
                return True
                
            result = subprocess.run(['which', 'chromium-browser'], 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    timeout=5)
            if result.returncode == 0:
                return True
                
            result = subprocess.run(['which', 'chrome'], 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    timeout=5)
            if result.returncode == 0:
                return True
                
        return False
    except:
        # If we can't check, assume it's not available rather than crash
        return False


class SeleniumScraper:
    """Selenium-based scraper for extracting business leads from Google Maps."""
    
    def __init__(self, config, headless=False, guest_mode=True, profile=None, delay=1.5):
        """Initialize the Selenium scraper."""
        self.config = config
        self.headless = headless
        self.guest_mode = guest_mode
        self.profile = profile
        self.delay = delay
        self.logger = logging.getLogger(__name__)
        self.robots_checker = RobotsChecker(config)
        self.driver = None
        self.wait = None
        
        # Check if Chrome is available before initializing
        chrome_available = is_chrome_available()
        if not chrome_available:
            self.logger.warning("Chrome/Chromium not found on system. Selenium scraper may not work in this environment.")
            # Still try to initialize, but user should be aware of potential issues
            print("⚠️  Warning: Chrome/Chromium not found on system.")
            print("   This may cause issues in deployment environments like Streamlit Cloud.")
            print("   Consider using alternative scraping methods for deployment.")
        
        try:
            self._setup_driver()
        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome WebDriver: {e}")
            if "Streamlit" in str(type(sys.modules.get('streamlit', ''))):
                # We're in Streamlit environment
                print("\n🚨 Google Maps scraping requires Chrome browser and may not work in cloud deployment environments.")
                print("   For local use: Install Chrome browser and run locally.")
                print("   For cloud deployment: Consider using alternative data sources.\n")
            raise
        except SystemExit:
            # Handle system exit exceptions
            pass
    
    def _setup_driver(self):
        """Set up Chrome WebDriver with appropriate options."""
        self.logger.info("Setting up Chrome WebDriver...")
        
        options = webdriver.ChromeOptions()
        
        if self.guest_mode and not self.profile:
            self.logger.info("Launching Chrome in Guest mode")
            options.add_argument('--guest')
        elif self.profile:
            self.logger.info(f"Launching Chrome with profile: {self.profile}")
            
            system = platform.system()
            if system == 'Windows':
                user_data_dir = os.path.join(
                    os.environ['LOCALAPPDATA'],
                    'Google', 'Chrome', 'User Data'
                )
            elif system == 'Darwin':
                user_data_dir = os.path.expanduser(
                    '~/Library/Application Support/Google/Chrome'
                )
            else:
                user_data_dir = os.path.expanduser('~/.config/google-chrome')
            
            options.add_argument(f'--user-data-dir={user_data_dir}')
            options.add_argument(f'--profile-directory={self.profile}')
        
        # Essential options for Linux/Docker environments - these are critical
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-plugins-discovery')
        options.add_argument('--disable-background-timer-throttling')
        options.add_argument('--disable-backgrounding-occluded-windows')
        options.add_argument('--disable-renderer-backgrounding')
        options.add_argument('--disable-features=TranslateUI')
        options.add_argument('--disable-ipc-flooding-protection')
        options.add_argument('--disable-background-networking')
        options.add_argument('--disable-default-apps')
        options.add_argument('--disable-features=VizDisplayCompositor')
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-accelerated-2d-canvas')
        options.add_argument('--no-first-run')
        options.add_argument('--no-zygote')
        options.add_argument('--disable-features=VizDisplayCompositor')
        options.add_argument('--disable-logging')
        options.add_argument('--disable-permissions-api')
        options.add_argument('--disable-web-security')
        options.add_argument('--allow-running-insecure-content')
        options.add_argument('--disable-site-isolation-trials')
        
        # Anti-detection options
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-features=UserAgentClientHint')
        options.add_argument('--disable-features=Translate')
        
        # Headless operation
        options.add_argument('--headless=new')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--lang=en-US')
        
        # Experimental options for better compatibility
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.notifications": 2,
            "profile.default_content_settings.popups": 0,
            "profile.managed_default_content_settings.images": 2
        })
        
        try:
            # Use ChromeDriverManager to get the correct ChromeDriver
            chrome_driver_path = ChromeDriverManager().install()
            service = Service(chrome_driver_path)
            
            # Suppress ChromeDriver logs by redirecting to devnull
            service.log_path = "NUL" if os.name == "nt" else "/dev/null"
            
            self.driver = webdriver.Chrome(service=service, options=options)
            
            self.driver.set_page_load_timeout(
                self.config.selenium['page_load_timeout']
            )
            
            self.wait = WebDriverWait(self.driver, 15)
            
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            
            # Additional stealth scripts
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})"
            )
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})"
            )
            self.driver.execute_script(
                "const newProto = navigator.__proto__;\n                delete newProto.webdriver;\n                navigator.__proto__ = newProto;"
            )
            
            self.logger.info("✓ Chrome WebDriver initialized successfully")
            
        except WebDriverException as e:
            if "unexpectedly exited. Status code was: 127" in str(e):
                self.logger.error("ChromeDriver failed to start - missing system libraries in deployment environment")
                print("\n🚨 ChromeDriver Error: Missing system libraries")
                print("   This commonly occurs in deployment environments like Streamlit Cloud")
                print("   where essential Linux libraries for Chrome are not available.")
                print("   \n💡 SOLUTIONS:")
                print("   - For local use: Install Chrome browser and required system libraries")
                print("   - For cloud deployment: Use alternative scraping methods or self-hosted solutions")
                print("   - Contact your hosting provider for Chrome-compatible environment\n")
            raise
        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome WebDriver: {e}")
            raise
    
    def scrape_google_maps(
        self,
        query: str,
        location: str,
        max_results: int = 100,
        tile_mode: bool = False,
        tile_size: float = 0.1
    ) -> List[Dict]:
        """Scrape business leads from Google Maps."""
        all_leads = []
        
        if not self._check_robots_txt('https://www.google.com/maps'):
            self.logger.error("Scraping not allowed by robots.txt")
            return all_leads
        
        self.logger.info("Navigating to Google Maps...")
        self.driver.get('https://www.google.com/maps')
        sleep_random(3, 1)
        
        if self._detect_captcha():
            self._handle_captcha()
        
        search_query = f"{query} {location}"
        self.logger.info(f"Searching for: {search_query}")
        
        if not self._perform_search(search_query):
            self.logger.error("Search failed")
            return all_leads
        
        self.logger.info("Waiting for results to load...")
        sleep_random(4, 1)
        
        leads = self._extract_results(max_results)
        all_leads.extend(leads)
        
        self.logger.info(f"✓ Extracted {len(leads)} businesses")
        
        return all_leads
    
    def _check_robots_txt(self, url: str) -> bool:
        """Check if scraping is allowed by robots.txt."""
        if not self.config.robots['enabled']:
            return True
        
        self.logger.info(f"Checking robots.txt for {url}")
        allowed = self.robots_checker.can_fetch(url)
        
        if allowed:
            self.logger.info("✓ Scraping allowed by robots.txt")
        else:
            self.logger.warning("✗ Scraping disallowed by robots.txt")
        
        return allowed
    
    def _perform_search(self, query: str) -> bool:
        """Perform search on Google Maps."""
        try:
            search_box = None
            
            # Method 1: Try the original ID selector
            try:
                search_box = self.wait.until(
                    EC.presence_of_element_located((By.ID, 'searchboxinput'))
                )
                self.logger.debug("Found search box with ID 'searchboxinput'")
            except TimeoutException:
                pass
            
            # Method 2: Try the name attribute (found by diagnostic)
            if not search_box:
                try:
                    search_box = self.wait.until(
                        EC.presence_of_element_located((By.NAME, 'q'))
                    )
                    self.logger.debug("Found search box with NAME 'q'")
                except TimeoutException:
                    pass
            
            # Method 3: Try updated selectors for 2025 Google Maps
            if not search_box:
                try:
                    search_box = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[id*="search"]'))
                    )
                    self.logger.debug("Found search box with CSS 'input[id*=\"search\"]'")
                except TimeoutException:
                    pass
            
            # Method 4: Try by placeholder attribute
            if not search_box:
                try:
                    search_box = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder*="Search" i]'))
                    )
                    self.logger.debug("Found search box with placeholder")
                except TimeoutException:
                    pass
            
            # Method 5: Try by aria-label attribute
            if not search_box:
                try:
                    search_box = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'input[aria-label*="Search" i]'))
                    )
                    self.logger.debug("Found search box with aria-label")
                except TimeoutException:
                    pass
            
            # Method 6: Try any input in search area
            if not search_box:
                try:
                    search_box = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '#searchbox-form input, .searchbox input, [data-attr*="search"] input'))
                    )
                    self.logger.debug("Found search box with form selector")
                except TimeoutException:
                    pass
            
            if not search_box:
                self.logger.error("Search box not found with any selector")
                return False
            
            search_box.clear()
            sleep_random(0.5, 0.2)
            
            for char in query:
                search_box.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
            
            sleep_random(0.5, 0.2)
            search_box.send_keys(Keys.RETURN)
            
            self.logger.info("✓ Search submitted")
            return True
            
        except TimeoutException:
            self.logger.error("Search box not found")
            return False
        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            return False
    
    def _extract_results(self, max_results: int) -> List[Dict]:
        """Extract business information from search results - FIXED FOR 2025."""
        leads = []
        processed_names = set()
        
        try:
            results_panel = None
            
            # Method 1: Try the original feed selector
            try:
                results_panel = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="feed"]'))
                )
                self.logger.debug("Found results panel with 'div[role=\"feed\"]'")
            except TimeoutException:
                pass
            
            # Method 2: Try updated selectors for 2025
            if not results_panel:
                try:
                    results_panel = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '[role="main"] div[role="feed"], .search-results, .results-panel'))
                    )
                    self.logger.debug("Found results panel with updated selectors")
                except TimeoutException:
                    pass
            
            # Method 3: Try from diagnostic findings - search-related area
            if not results_panel:
                try:
                    results_panel = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '[jsaction*="search" i], [aria-label*="search" i] + div, div[role="main"]'))
                    )
                    self.logger.debug("Found results panel from diagnostic findings")
                except TimeoutException:
                    pass
            
            # Method 4: Try any scrollable results area
            if not results_panel:
                try:
                    results_panel = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'div[aria-label*="results" i], div[data-section*="results" i], .scrollable-results'))
                    )
                    self.logger.debug("Found results panel with aria-label")
                except TimeoutException:
                    pass
            
            if not results_panel:
                self.logger.warning("Results panel not found with any selector")
                return leads
            
            sleep_random(3, 0.5)
            self.logger.info("✓ Results panel found")
        except TimeoutException:
            self.logger.warning("Results panel not found")
            return leads
        
        scroll_attempts = 0
        max_scroll_attempts = self.config.scraping['max_scroll_attempts']
        no_new_results_count = 0
        
        while len(leads) < max_results and scroll_attempts < max_scroll_attempts:
            try:
                # Find all result links with multiple fallback selectors
                result_elements = []
                
                # Method 1: Original selector
                elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    'div[role="feed"] > div > div > a'
                )
                if elements:
                    result_elements.extend(elements)
                    self.logger.debug(f"Found {len(elements)} elements with original selector")
                
                # Method 2: From diagnostic - search result items
                elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    'a[data-value][href*="/place"], [data-result-index] a, [jsaction*="result" i] a'
                )
                if elements:
                    result_elements.extend(elements)
                    self.logger.debug(f"Found {len(elements)} elements with diagnostic selectors")
                
                # Method 3: Updated selectors for 2025
                elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    'a[href*="/maps/place/"], [data-value*="place"], .result-item a, .search-result a'
                )
                if elements:
                    result_elements.extend(elements)
                    self.logger.debug(f"Found {len(elements)} elements with updated selectors")
                
                # Method 4: Any links in results area
                elements = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    '[role="feed"] a, [role="main"] a[href*="/maps/"], .results-list a'
                )
                if elements:
                    result_elements.extend(elements)
                    self.logger.debug(f"Found {len(elements)} elements with generic selectors")
                
                # Remove duplicates by href
                seen_hrefs = set()
                unique_elements = []
                for elem in result_elements:
                    href = elem.get_attribute('href') or ''
                    if href and href not in seen_hrefs:
                        seen_hrefs.add(href)
                        unique_elements.append(elem)
                
                result_elements = unique_elements
                
                self.logger.info(f"Found {len(result_elements)} result elements on page")
                
                current_leads_count = len(leads)
                
                for idx, element in enumerate(result_elements):
                    if len(leads) >= max_results:
                        break
                    
                    try:
                        # UPDATED: Multiple fallback methods for business name
                        business_name = None
                        
                        # Method 1: aria-label attribute (MOST RELIABLE)
                        try:
                            aria_label = element.get_attribute('aria-label')
                            if aria_label and len(aria_label) > 2:
                                business_name = aria_label.strip()
                                self.logger.debug(f"Name from aria-label: {business_name}")
                        except:
                            pass
                        
                        # Method 2: Get text from any div inside
                        if not business_name:
                            try:
                                divs = element.find_elements(By.TAG_NAME, 'div')
                                for div in divs:
                                    text = div.text.strip()
                                    # Look for text that seems like a business name
                                    if text and 3 < len(text) < 100 and '\n' not in text:
                                        business_name = text
                                        self.logger.debug(f"Name from div: {business_name}")
                                        break
                            except:
                                pass
                        
                        # Method 3: All text from element (last resort)
                        if not business_name:
                            try:
                                all_text = element.text.strip()
                                if all_text:
                                    # Take first line, max 100 chars
                                    business_name = all_text.split('\n')[0][:100]
                                    self.logger.debug(f"Name from element text: {business_name}")
                            except:
                                pass
                        
                        # Skip if no name or duplicate
                        if not business_name or business_name in processed_names:
                            self.logger.debug(f"Skipping: no name or duplicate")
                            continue
                        
                        # Skip common non-business text
                        skip_words = ['more places', 'see more', 'show more', 'load more', 'results']
                        if any(word in business_name.lower() for word in skip_words):
                            continue
                        
                        self.logger.info(f"Processing ({len(leads)+1}/{max_results}): {business_name}")
                        processed_names.add(business_name)
                        
                        # Scroll into view
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});",
                            element
                        )
                        sleep_random(0.5, 0.2)
                        
                        # Click element
                        try:
                            element.click()
                        except:
                            self.driver.execute_script("arguments[0].click();", element)
                        
                        sleep_random(self.delay * 1.5, 0.5)
                        
                        # Extract detailed information
                        business_data = self._extract_business_details_simple(business_name)
                        
                        if business_data:
                            leads.append(business_data)
                            self.logger.info(f"✓ Extracted: {business_name}")
                        
                        if self._detect_captcha():
                            self._handle_captcha()
                        
                    except Exception as e:
                        self.logger.debug(f"Error processing result {idx}: {e}")
                        continue
                
                # Check if we got new results
                if len(leads) == current_leads_count:
                    no_new_results_count += 1
                    self.logger.info(f"No new results (attempt {no_new_results_count}/3)")
                    if no_new_results_count >= 3:
                        self.logger.info("Stopping - no new results after 3 attempts")
                        break
                else:
                    no_new_results_count = 0
                
                # Scroll for more results
                if len(leads) < max_results:
                    self.logger.info(f"Scrolling... ({len(leads)}/{max_results})")
                    self._scroll_results_panel()
                    scroll_attempts += 1
                    sleep_random(self.config.scraping['scroll_delay'], 0.5)
                
            except Exception as e:
                self.logger.error(f"Error in extraction loop: {e}", exc_info=True)
                break
        
        return leads
    
    def _extract_business_details_simple(self, name: str) -> Optional[Dict]:
        """Extract business details from detail panel with EMAIL."""
        try:
            sleep_random(1.5, 0.3)
            
            current_url = self.driver.current_url
            place_id = self._extract_place_id(current_url)
            
            # Extract address
            address = (
                self._safe_extract(By.CSS_SELECTOR, 'button[data-item-id="address"] div.fontBodyMedium', 'text') or
                self._safe_extract(By.CSS_SELECTOR, 'button[data-tooltip="Copy address"]', 'aria-label') or
                self._safe_extract(By.XPATH, '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]', 'text')
            )
            
            # Extract phone
            phone = (
                self._safe_extract(By.CSS_SELECTOR, 'button[data-tooltip="Copy phone number"]', 'aria-label') or
                self._safe_extract(By.CSS_SELECTOR, 'button[data-item-id*="phone"]', 'aria-label')
            )
            if phone and ':' in phone:
                phone = phone.split(':')[-1].strip()
            
            # Extract website
            website = (
                self._safe_extract(By.CSS_SELECTOR, 'a[data-item-id="authority"]', 'href') or
                self._safe_extract(By.CSS_SELECTOR, 'a[data-tooltip="Open website"]', 'href')
            )
            
            # EMAIL EXTRACTION
            email = None
            try:
                page_source = self.driver.page_source
                email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                emails_found = re.findall(email_pattern, page_source)
                
                filtered_emails = [
                    e for e in emails_found 
                    if not any(x in e.lower() for x in [
                        'google', 'gstatic', 'schema', 'example', 'placeholder',
                        'noreply', 'no-reply', 'donotreply'
                    ])
                ]
                
                if filtered_emails:
                    email = filtered_emails[0]
                    self.logger.debug(f"Found email: {email}")
            except:
                pass
            
            if not email and website:
                try:
                    email = self._extract_email_from_website(website)
                except:
                    pass
            
            # Extract category
            category = self._safe_extract(By.CSS_SELECTOR, 'button[jsaction*="category"]', 'text')
            
            # Extract rating
            rating_text = self._safe_extract(By.CSS_SELECTOR, 'div.F7nice > span[aria-hidden="true"]', 'text')
            rating = self._parse_rating(rating_text)
            
            # Extract reviews
            reviews_text = self._safe_extract(By.CSS_SELECTOR, 'div.F7nice > span > span > span[aria-label]', 'aria-label')
            reviews = self._parse_reviews(reviews_text)
            
            # Extract coordinates
            coords = self._extract_coordinates(current_url)
            
            business = {
                'place_id': place_id,
                'name': name,
                'address': address,
                'phone': phone,
                'email': email,
                'website': website,
                'category': category,
                'rating': rating,
                'reviews': reviews,
                'latitude': coords[0] if coords else None,
                'longitude': coords[1] if coords else None,
                'maps_url': current_url,
                'source_url': current_url,
                'timestamp': datetime.now().isoformat(),
                'labels': None
            }
            
            return business
            
        except Exception as e:
            self.logger.warning(f"Failed to extract details for {name}: {e}")
            return {
                'place_id': None,
                'name': name,
                'address': None,
                'phone': None,
                'email': None,
                'website': None,
                'category': None,
                'rating': None,
                'reviews': None,
                'latitude': None,
                'longitude': None,
                'maps_url': self.driver.current_url,
                'source_url': self.driver.current_url,
                'timestamp': datetime.now().isoformat(),
                'labels': None
            }
    
    def _extract_email_from_website(self, website_url: str, timeout: int = 5) -> Optional[str]:
        """Extract email from business website."""
        try:
            import requests
            from requests.exceptions import RequestException
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(
                website_url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                verify=True
            )
            
            if response.status_code == 200:
                email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                emails = re.findall(email_pattern, response.text)
                
                filtered = [
                    e for e in emails 
                    if not any(x in e.lower() for x in [
                        'example.com', 'test.com', 'sample.com', 
                        'wix.com', 'wordpress.com', 'yourdomain.com',
                        'sentry.io', 'privacy@', 'noreply@'
                    ])
                ]
                
                if filtered:
                    return filtered[0]
            
        except:
            pass
        
        return None
    
    def _safe_extract(self, by: By, selector: str, attribute: str = 'text') -> Optional[str]:
        """Safely extract element content."""
        try:
            element = self.driver.find_element(by, selector)
            
            if attribute == 'text':
                return element.text.strip() if element.text else None
            else:
                return element.get_attribute(attribute)
                
        except:
            return None
    
    def _extract_place_id(self, url: str) -> Optional[str]:
        """Extract place_id from URL."""
        match = re.search(r'!1s(0x[0-9a-f]+:0x[0-9a-f]+)', url)
        if match:
            return match.group(1)
        
        match = re.search(r'cid=(\d+)', url)
        if match:
            return match.group(1)
        
        return None
    
    def _extract_coordinates(self, url: str) -> Optional[Tuple[float, float]]:
        """Extract coordinates from URL."""
        match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if match:
            return (float(match.group(1)), float(match.group(2)))
        return None
    
    def _parse_rating(self, text: Optional[str]) -> Optional[float]:
        """Parse rating from text."""
        if not text:
            return None
        
        try:
            match = re.search(r'(\d+\.?\d*)', text)
            if match:
                rating = float(match.group(1))
                return rating if 0 <= rating <= 5 else None
        except:
            return None
        
        return None
    
    def _parse_reviews(self, text: Optional[str]) -> Optional[int]:
        """Parse reviews from text."""
        if not text:
            return None
        
        try:
            match = re.search(r'(\d+(?:,\d+)*)', text)
            if match:
                return int(match.group(1).replace(',', ''))
        except:
            return None
        
        return None
    
    def _scroll_results_panel(self):
        """Scroll results panel."""
        try:
            results_panel = self.driver.find_element(
                By.CSS_SELECTOR,
                'div[role="feed"]'
            )
            
            self.driver.execute_script(
                'arguments[0].scrollTo(0, arguments[0].scrollHeight)',
                results_panel
            )
            
        except Exception as e:
            self.logger.debug(f"Error scrolling: {e}")
    
    def _detect_captcha(self) -> bool:
        """Detect captcha."""
        captcha_indicators = [
            'g-recaptcha',
            'recaptcha',
            'captcha',
            'verify you are human',
            'unusual traffic'
        ]
        
        page_source = self.driver.page_source.lower()
        
        for indicator in captcha_indicators:
            if indicator in page_source:
                return True
        
        return False
    
    def _handle_captcha(self):
        """Handle captcha."""
        print("\n" + "="*70)
        print("⚠️  CAPTCHA DETECTED!")
        print("="*70)
        print("\nPlease solve the captcha manually in the Chrome window.")
        print("Then press ENTER here to continue...\n")
        print("="*70 + "\n")
        
        self.logger.warning("Captcha detected - waiting for manual intervention")
        input()
        self.logger.info("Resuming after captcha resolution")
        sleep_random(2, 0.5)
    
    def close(self):
        """Close browser."""
        if self.driver:
            self.logger.info("Closing browser...")
            try:
                self.driver.quit()
            except Exception as e:
                self.logger.warning(f"Error closing browser: {e}")
