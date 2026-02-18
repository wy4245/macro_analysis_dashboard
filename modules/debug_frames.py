import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

def debug_frames():
    options = Options()
    # options.add_argument("--headless=new") # Debug with window visible if needed
    options.add_argument("--window-size=1920,1080")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        print("Connecting to Kofia Bond...")
        driver.get("https://www.kofiabond.or.kr/index.html")
        time.sleep(5)
        
        def dump_frames(current_frame_name="Top"):
            print(f"\n--- Frame: {current_frame_name} ---")
            print(f"URL: {driver.current_url}")
            
            # Save source for inspection
            filename = f"debug_{current_frame_name.replace('>', '_').replace(' ', '_')}.html"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print(f"Saved {filename}")
            
            if "기간별" in driver.page_source:
                print(f"!!! FOUND '기간별' in {current_frame_name} !!!")
            
            if "국고채" in driver.page_source:
                print(f"!!! FOUND '국고채' in {current_frame_name} !!!")

            if "chkAnnItm_input_14" in driver.page_source:
                print(f"!!! FOUND 'chkAnnItm_input_14' in {current_frame_name} !!!")
                
            if "image4" in driver.page_source:
                print(f"!!! FOUND 'image4' in {current_frame_name} !!!")

            frames = driver.find_elements(By.XPATH, "//frame | //iframe")
            print(f"Found {len(frames)} sub-frames")
            
            for i, frame in enumerate(frames):
                f_id = frame.get_attribute("id")
                f_name = frame.get_attribute("name")
                f_tag = frame.tag_name
                print(f"  [{i}] Tag: {f_tag}, ID: {f_id}, Name: {f_name}")
                
            # Try to switch and recurse
            for i in range(len(frames)):
                try:
                    driver.switch_to.frame(i)
                    dump_frames(f"{current_frame_name}>{i}")
                    driver.switch_to.parent_frame()
                except Exception as e:
                    print(f"  Could not enter frame {i}: {e}")

        # Start process
        # First click menu to load maincontent
        print("Clicking menu items...")
        driver.switch_to.frame("fraAMAKMain")
        
        def safe_click(by, value):
            try:
                el = driver.find_element(by, value)
                driver.execute_script("arguments[0].click();", el)
                return True
            except:
                return False

        safe_click(By.ID, "genLv1_0_imgLv1")
        time.sleep(1)
        safe_click(By.ID, "genLv1_0_genLv2_0_txtLv2")
        time.sleep(5)
        
        driver.switch_to.default_content()
        dump_frames()

    finally:
        driver.quit()

if __name__ == "__main__":
    debug_frames()
