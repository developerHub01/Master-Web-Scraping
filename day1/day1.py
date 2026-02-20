from random import uniform
from time import sleep
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, Page
from playwright.sync_api import Error
import sqlite3

WEBSITE_URL = "https://books.toscrape.com"

rating_map = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}

product_info_map = {
    "UPC": "upc",
    "Product Type": "product_type",
    "Price (excl. tax)": "price_without_tax",
    "Price (incl. tax)": "price_with_tax",
    "Tax": "tax",
    "Availability": "availability",
    "Number of reviews": "number_of_reviews",
}


def search_books_page(db_cursor: sqlite3.Cursor, db_conn: sqlite3.Connection, page: Page, index: int = 0):
    print(f"page number === {index + 1}")
    print(page.url)
    books = []

    page.wait_for_load_state("domcontentloaded")
    page.wait_for_selector(".product_pod")
    books_locator = page.locator(".product_pod").all()

    for book in books_locator:
        sub_url = book.locator("h3 a").get_attribute("href")
        if not sub_url:
            print(f"""
            no url found 
            ===>>  {sub_url}
            """)
            continue
        sub_url = sub_url.strip()

        sub_url = urljoin(page.url, sub_url)
        print(sub_url)
        thumbnail = book.locator(".image_container img").first.get_attribute("src")
        thumbnail = urljoin(WEBSITE_URL, thumbnail) if thumbnail else None

        books.append((sub_url, thumbnail))

    db_cursor.executemany("""
        insert or ignore into books (link, thumbnail) values (?, ?)
    """, books)
    db_conn.commit()

    try:
        next_locator = page.locator(".pager .next a")
        if not next_locator.count():
            raise Error("")

        page.evaluate("window.scrollBy(0, window.innerHeight)")
        sleep(uniform(1, 3.5))

        next_locator.click()
        search_books_page(db_cursor=db_cursor, db_conn=db_conn, page=page, index=index + 1)
    except Error:
        print("no next page")


def get_books_details(db_cursor: sqlite3.Cursor, db_conn: sqlite3.Connection, page: Page):
    rows = list(map(lambda x: x[0], db_cursor.execute("""
        select link from books
    """).fetchall()))
    for index, url in enumerate(rows):
        search_by_url(db_cursor=db_cursor, db_conn=db_conn, page=page, url=url)
        print(f"{index + 1} / {len(rows)}")


def search_by_url(db_cursor: sqlite3.Cursor, db_conn: sqlite3.Connection, page: Page, url: str):
    print(url)
    try:
        book_details = {}
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(".page_inner")

        if not page.locator(".page_inner").count():
            try:
                db_cursor.execute(f"delete from books where link = '{url}'")
                db_conn.commit()
            except sqlite3.Error:
                pass
            return

        try:
            page.wait_for_selector(".breadcrumb li a")
            book_details["category"] = page.locator(".breadcrumb li a").nth(2).inner_text().strip()
        except Error:
            print("category not found")

        try:
            page.wait_for_selector(".product_page .product_main h1")
            book_details["name"] = page.locator(".product_page .product_main h1").inner_text()
        except Error:
            print("name not found")

        try:
            page.wait_for_selector("#product_gallery .thumbnail .active img")
            src = page.locator("#product_gallery .thumbnail .active img").get_attribute(
                "src").strip()
            if not src: raise Error("")
            book_details["image"] = urljoin(WEBSITE_URL, src)
        except Error:
            print("image not found")

        try:
            page.wait_for_selector("#product_description+p")
            book_details["description"] = page.locator("#product_description+p").inner_text().strip()
        except Error:
            print("description not found")

        try:
            page.wait_for_selector(".star-rating")
            rating = page.locator(".star-rating").first.get_attribute("class").split(" ")[-1].lower().strip()
            if rating not in rating_map: raise Error("")
            book_details["rating"] = rating_map[rating]
        except Error:
            print("rating not found")

        try:
            page.wait_for_selector("table.table.table-striped tr")
            book_info_rows = page.locator("table.table.table-striped tr").all()
            for row in book_info_rows:
                key = product_info_map[row.locator("th").inner_text().strip()]
                value = row.locator("td").inner_text().strip()
                if not key: raise Error("")

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
        db_cursor.execute(f"""
            update books set {", ".join(updates)} where link = ?
        """, values)
        db_conn.commit()
    except Error:
        print(Error)


def main():
    with sync_playwright() as p:
        db_conn = sqlite3.connect("books.db")
        cursor = db_conn.cursor()

        cursor.execute("""
            create table if not exists books(
                link text primary key,
                name text,
                price_with_tax real,
                price_without_tax real,
                tax real,
                rating integer,
                thumbnail text,
                image text,
                category text,
                description text,
                upc text,
                product_type text,
                availability integer,
                number_of_reviews integer
            )""")
        db_conn.commit()

        browser = p.chromium.launch(headless=True)

        page = browser.new_page()
        page.goto(WEBSITE_URL, wait_until="domcontentloaded")

        # search_books_page(db_cursor=cursor, db_conn=db_conn, page=page)
        # print("books link listing completed...........")
        # get_books_details(db_cursor=cursor, db_conn=db_conn, page=page)
        # print("books details listing completed...........")
        # print("""===========================================
        # ================ MISSION ACCOMPLISED =================
        # ===========================================""")

        browser.close()
        db_conn.close()


if __name__ == "__main__":
    main()
