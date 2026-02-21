from random import uniform
from time import sleep
from urllib.parse import urljoin

from playwright.sync_api import Error
import sqlite3


class Scrapper:
    WEBSITE_URL = "https://books.toscrape.com"

    RATING_MAP = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
    }

    PRODUCT_INFO_MAP = {
        "UPC": "upc",
        "Product Type": "product_type",
        "Price (excl. tax)": "price_without_tax",
        "Price (incl. tax)": "price_with_tax",
        "Tax": "tax",
        "Availability": "availability",
        "Number of reviews": "number_of_reviews",
    }

    def __init__(self):
        self.db_conn = sqlite3.connect("books.db")
        self.db_cursor = self.db_conn.cursor()
        self.browser = None
        self.page = None
        self.setup_db()

    def setup_db(self):
        self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS books(
                link TEXT PRIMARY KEY,
                name TEXT,
                price_with_tax REAL,
                price_without_tax REAL,
                tax REAL,
                rating INTEGER,
                thumbnail TEXT,
                image TEXT,
                category TEXT,
                description TEXT,
                upc TEXT,
                product_type TEXT,
                availability INTEGER,
                number_of_reviews INTEGER
        )""")
        self.db_conn.commit()

    def run(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            self.browser = p.chromium.launch(headless=True)

            self.page = self.browser.new_page()

            # self.page.route("**/*.{png,jpg,jpeg,webp,gif,svg}", lambda route: route.abort())
            # self.page.route("**/*.{woff,woff2,ttf}", lambda route: route.abort())

            self.page.goto(self.WEBSITE_URL, wait_until="domcontentloaded")

            self.search_books_page()
            print("books link listing completed...........")
            self.get_books_details()
            print("books details listing completed...........")
            print("""===========================================
            ================ MISSION ACCOMPLISED =================
            ===========================================""")

            self.preview_data()

            self.browser.close()
            self.db_conn.close()

    def search_books_page(self, index: int = 0):
        print(f"page number === {index + 1}")
        print(self.page.url)
        books = []

        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_selector(".product_pod")
        books_locator = self.page.locator(".product_pod").all()

        for book in books_locator:
            sub_url = book.locator("h3 a").get_attribute("href")
            if not sub_url:
                print(f"""
                no url found 
                ===>>  {sub_url}
                """)
                continue
            sub_url = sub_url.strip()

            sub_url = urljoin(self.page.url, sub_url)
            print(sub_url)
            thumbnail = book.locator(".image_container img").first.get_attribute("src")
            thumbnail = urljoin(self.WEBSITE_URL, thumbnail) if thumbnail else None

            books.append((sub_url, thumbnail))

        self.db_cursor.executemany("""
            INSERT OR IGNORE INTO books (link, thumbnail) VALUES (?, ?)
        """, books)
        self.db_conn.commit()

        try:
            next_locator = self.page.locator(".pager .next a")
            if not next_locator.count():
                raise Error("")

            self.page.evaluate("window.scrollBy(0, window.innerHeight)")
            sleep(uniform(1, 3.5))

            next_locator.click()
            self.search_books_page(index=index + 1)
        except Error:
            print("no next page")

    def get_books_details(self):
        rows = list(map(lambda x: x[0], self.db_cursor.execute("""
            SELECT link FROM books
        """).fetchall()))
        for index, url in enumerate(rows):
            self.search_by_url(url=url)
            print(f"{index + 1} / {len(rows)}")

    def search_by_url(self, url: str):
        print(url)
        try:
            book_details = {}
            self.page.goto(url, wait_until="domcontentloaded")
            self.page.wait_for_selector(".page_inner")

            if not self.page.locator(".page_inner").count():
                try:
                    self.db_cursor.execute(f"DELETE FROM books WHERE link = '{url}'")
                    self.db_conn.commit()
                except sqlite3.Error:
                    pass
                return

            try:
                self.page.wait_for_selector(".breadcrumb li a")
                book_details["category"] = self.page.locator(".breadcrumb li a").nth(2).inner_text().strip()
            except Error:
                print("category not found")

            try:
                self.page.wait_for_selector(".product_page .product_main h1")
                book_details["name"] = self.page.locator(".product_page .product_main h1").inner_text()
            except Error:
                print("name not found")

            try:
                self.page.wait_for_selector("#product_gallery .thumbnail .active img")
                src = self.page.locator("#product_gallery .thumbnail .active img").get_attribute(
                    "src").strip()
                if not src: raise Error("")
                book_details["image"] = urljoin(self.WEBSITE_URL, src)
            except Error:
                print("image not found")

            try:
                self.page.wait_for_selector("#product_description+p")
                book_details["description"] = self.page.locator("#product_description+p").inner_text().strip()
            except Error:
                print("description not found")

            try:
                self.page.wait_for_selector(".star-rating")
                rating = self.page.locator(".star-rating").first.get_attribute("class").split(" ")[-1].lower().strip()
                if rating not in self.RATING_MAP: raise Error("")
                book_details["rating"] = self.RATING_MAP[rating]
            except Error:
                print("rating not found")

            try:
                self.page.wait_for_selector("table.table.table-striped tr")
                book_info_rows = self.page.locator("table.table.table-striped tr").all()
                for row in book_info_rows:
                    key = row.locator("th").inner_text()
                    if not key: continue
                    key = self.PRODUCT_INFO_MAP[key.strip()]

                    value = row.locator("td").inner_text()
                    value = value.strip() if value else None

                    if not key:
                        raise Error("")

                    if key == "number_of_reviews":
                        book_details[key] = int(value) if value else 0
                    elif key in ["price_without_tax", "price_with_tax", "tax"]:
                        value = value.removeprefix("£")
                        book_details[key] = float(value) if value else None
                    elif key == "availability":
                        value = value.removeprefix("In stock (").removesuffix(" available)")
                        book_details[key] = float(value) if value else 0
                    else:
                        book_details[key] = value

            except Error:
                print("UPC not found")

            updates = []
            values = []
            for key, value in book_details.items():
                updates.append(f"{key} = ?")
                values.append(value)

            values.append(url)
            self.db_cursor.execute(f"""
                UPDATE books SET {", ".join(updates)} WHERE link = ?
            """, values)
            self.db_conn.commit()
        except Error:
            print(Error)

    def preview_data(self, limit: int = 5):
        rows = self.db_cursor.execute(f"SELECT * FROM books LIMIT ?", (limit,)).fetchall()
        print(self.db_cursor.description)
        columns = [desc[0] for desc in self.db_cursor.description]
        data_list = [dict(zip(columns, row)) for row in rows]

        import json
        print(json.dumps(data_list, indent=4))

        return data_list


if __name__ == "__main__":
    scrapper = Scrapper()
    scrapper.run()
