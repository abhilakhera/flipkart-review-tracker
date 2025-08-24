import os, json, re, time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# -------- Google Sheets auth from GitHub Secret (JSON content) ----------
GSHEET_SERVICE_ACCOUNT_JSON = os.environ.get("GSHEET_SERVICE_ACCOUNT_JSON")
if not GSHEET_SERVICE_ACCOUNT_JSON:
    raise RuntimeError("Missing env var GSHEET_SERVICE_ACCOUNT_JSON")

creds_dict = json.loads(GSHEET_SERVICE_ACCOUNT_JSON)
scope = ["https://www.googleapis.com/auth/spreadsheets",
         "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gc = gspread.authorize(creds)

SHEET_NAME = os.environ.get("SHEET_NAME", "Flipkart Review Tracker")
WORKSHEET_NAME = os.environ.get("WORKSHEET_NAME", "Sheet1")

sh = gc.open(SHEET_NAME)
sheet = sh.worksheet(WORKSHEET_NAME)

# -------- Selenium setup (headless Chrome for GitHub Actions) ----------
chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari")

driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 8)

RATING_SELECTOR = "div.DOjaWF div.cPHDOP div.C7fEHH div.ISksQ2 div._5OesEi div.XQDdHH"
RR_SELECTOR = "span.Wphh3N"

num_re = re.compile(r"\d+(?:\.\d+)?")

def extract_float(text):
    m = num_re.search(text or "")
    return float(m.group()) if m else None

def clean_rr_text(text):
    # Normalize spaces/newlines to: "129 Ratings & 21 Reviews"
    t = (text or "").replace("\n", " ").replace("\u00a0", " ")
    t = re.sub(r"\s*&\s*", " & ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def get_rating_and_rr(fsn_id):
    url = f"https://www.flipkart.com/product/p/itmf{fsn_id}?pid={fsn_id}"
    driver.get(url)

    rating_val = None
    rr_text = None

    try:
        el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, RATING_SELECTOR)))
        rating_val = extract_float(el.text)
    except Exception:
        pass

    try:
        el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, RR_SELECTOR)))
        rr_text = clean_rr_text(el.text)
    except Exception:
        pass

    return rating_val, rr_text

def update_sheet():
    # Read all rows as dicts (requires header row)
    rows = sheet.get_all_records()
    # Start=2 because row 1 is header
    for i, row in enumerate(rows, start=2):
        fsn = str(row.get("FSN", "")).strip()
        if not fsn:
            continue

        print(f"Processing FSN: {fsn}")
        rating, rr_text = get_rating_and_rr(fsn)

        if rating is None or rr_text is None:
            print(f"  -> Skipped (missing data).")
            continue

        # Read current cells
        old_rating = sheet.cell(i, 4).value  # D
        old_rr = sheet.cell(i, 5).value      # E

        # If Ratings & Reviews text changed, shift D/E into F/G first
        if old_rr and old_rr != rr_text:
            sheet.update_cell(i, 6, old_rating or "")  # F
            sheet.update_cell(i, 7, old_rr or "")      # G

        # Update current values
        sheet.update_cell(i, 4, rating)   # D
        sheet.update_cell(i, 5, rr_text)  # E

        print(f"  -> Updated: Rating={rating}, RR='{rr_text}'")

if __name__ == "__main__":
    try:
        update_sheet()
    finally:
        try:
            driver.quit()
        except Exception:
            pass

