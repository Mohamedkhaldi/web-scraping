import os
import json
from datetime import date
from pymongo import MongoClient
import csv
from datetime import date
from bs4 import BeautifulSoup
import requests
import concurrent.futures
from flask import Flask, render_template, request, redirect, url_for, session, flash
from bson import ObjectId # Import ObjectId
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Required for session management

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Set the login view function

# Helper function to convert ObjectId to strings
def convert_object_ids_to_strings(obj):
    if isinstance(obj, dict):
        return {key: convert_object_ids_to_strings(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_object_ids_to_strings(item) for item in obj]
    elif isinstance(obj, ObjectId):
        return str(obj)
    return obj

class User(UserMixin):
    def __init__(self, id, username, password, is_admin):
        self.id = id
        self.username = username
        self.password = password
        self.is_admin = is_admin

    def is_authenticated(self):
        return True

    def is_active(self):
         return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    try:
        client = MongoClient('mongodb://localhost:27017/')
        db = client['product_db']
        users_collection = db['users']

        user_data = users_collection.find_one({'_id':ObjectId(user_id)})
        if user_data:
            return User(str(user_data['_id']),user_data['username'], user_data['password'], user_data.get('is_admin', False))
        return None

    except Exception as e:
          print(f'Error in load user: {e}')
          return None
    finally:
       if client:
            client.close()

class AmazonProductScraper:
    def __init__(self):
        self.category_name = None
        self.formatted_category_name = None
        self.max_pages = 2 # Maximum number of pages to scrape

    def fetch_webpage_content(self, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36"
        }
        response = requests.get(url, headers=headers)
        return response.text

    def get_category_url(self, category_name):
        self.category_name = category_name
        self.formatted_category_name = self.category_name.replace(" ", "+")
        category_url = f"https://www.amazon.fr/s?k={self.formatted_category_name}&ref=nb_sb_noss"
        print(">> Category URL: ", category_url)
        return category_url

    def truncate_title(title, max_words=15):
        words = title.split()[:max_words]
        return ' '.join(words)

    @staticmethod
    def extract_product_information(page_results):
        temp_record = []
        for item in page_results:
            
            description_element = item.h2
            if description_element:
                span_element = description_element.find('span')
                if span_element:
                    description = span_element.text.strip()
                    prefix = "Lenovo IdeaPad 3 17ALC6 - Ordinateur Portable 17'' HD+ "
                    if description.startswith(prefix):
                        description = description[len(prefix):]
                else:
                      description=description_element.text.strip()
            
            else:
                description = "N/A"
            
            
            price_element = item.find('span', {"class":'a-offscreen'})
            
            if price_element:
                product_price = price_element.text
                if product_price:
                     
                     product_price= product_price
                     
                else:
                    product_price = "N/A"
            else:
                 product_price = "N/A"


            title_element = item.h2
            if title_element:
                span_element = title_element.find('span')
                if span_element:
                    product_title = span_element.text.strip().replace(',', '')
                    title = product_title.split()[:5]
                    name = ' '.join(title)
                else:
                     product_title=title_element.text.strip().replace(',', '')
                     title = product_title.split()[:5]
                     name = ' '.join(title)
            else:
                name = ""

            review_element = item.find('i')
            product_review = review_element.text.strip() if review_element else "N/A"

            review_number_element = item.find('span', {'class': 'a-size-base'})
            review_number = review_number_element.text if review_number_element else "N/A"
            
            image_element = item.find('img', class_='s-image')
            product_image = image_element['src']

            

            sold_element = item.div
            if sold_element:
                sp_element = sold_element.find('span', {"class":'a-size-base a-color-secondary'})
                if sp_element:
                    prodct_title = sp_element.text.strip().replace(',', '')
                    titl = prodct_title.split()[:10]
                    sold = ' '.join(titl)
                else:
                     prodct_title=sold_element.text.strip().replace(',', '')
                     titl = prodct_title.split()[:10]
                     sold = ' '.join(titl)
            else:
                sold = ""

            product_information = (name,product_price if product_price != "N/A" else "N/A",product_review,review_number, description,sold,product_image )
            temp_record.append(product_information)

            

        return temp_record

    def process_page(self, page_number, category_url):
        print(f">> Page {page_number} - webpage information extracted")
        next_page_url = category_url + f"&page={page_number}"
        page_content = self.fetch_webpage_content(next_page_url)
        soup = BeautifulSoup(page_content, 'html.parser')
        page_results = soup.find_all('div', {'data-component-type': 's-search-result'})
        return self.extract_product_information(page_results)

    def navigate_to_other_pages(self, category_url):
        records = []
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_page = {executor.submit(self.process_page, page_number, category_url): page_number for page_number in range(1, self.max_pages + 1)}
            for future in concurrent.futures.as_completed(future_to_page):
                page_number = future_to_page[future]
                try:
                    temp_record = future.result()
                    records += temp_record
                except Exception as e:
                    print(f"Exception occurred for page {page_number}: {e}")

        print("\n>> Creating an excel sheet and entering the details...")
        return records

    def product_information_json(self, records):
        today = date.today().strftime("%d-%m-%Y")
        file_name = f"{self.category_name}_{today}.json"

        # Convert records (assuming they are lists) to dictionaries
        keys = ['Title', 'Price', 'Rating', 'Review Count', 'Description','Sold','Image URL']
        dict_records = [dict(zip(keys, rec)) for rec in records]

        # Save to JSON file
        with open(file_name, "w", encoding='utf-8') as f:
            json.dump(dict_records, f, indent=4, ensure_ascii=False)

        message = f">> Information about the product '{self.category_name}' is stored in {file_name}\n"
        print(message)
        #os.startfile(file_name) # removed for production 

        # Save to MongoDB
        self.save_to_mongodb(dict_records)

    def save_to_mongodb(self, records):
        try:
            client = MongoClient('mongodb://localhost:27017/')
            db = client['product_db'] # Replace 'product_db' with your database name
            collection = db[self.category_name] # Collection name will match category
            collection.insert_many(records)

            print(f">> Data for '{self.category_name}' has been saved to MongoDB.")

        except Exception as e:
            print(f"Error saving to MongoDB: {e}")
        finally:
            if client:
                client.close()

def get_products_from_mongodb(category_name):
    try:
        client = MongoClient('mongodb://localhost:27017/')
        db = client['product_db']
        collection = db[category_name]
        products = list(collection.find())
        return products
    except Exception as e:
            print(f"Error fetching data from MongoDB: {e}")
            return None
    finally:
        if client:
            client.close()

    # User registration
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
         # Check if the username already exists
        try:
            client = MongoClient('mongodb://localhost:27017/')
            db = client['product_db']
            users_collection = db['users']

            if users_collection.find_one({'username':username}):
                flash('Username already taken, please chose another one ', 'danger')
                return redirect(url_for('register'))


            # Hash password
            hashed_password = generate_password_hash(password)

            #add new user to dict
            new_user = {
                'username': username,
                'password': hashed_password,
                'is_admin': False
                }
            users_collection.insert_one(new_user)
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            flash(f'Error saving new user: {e}', 'danger')
            return redirect(url_for('register'))
        finally:
            if client:
                client.close()


    return render_template('register.html')

   # User login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            client = MongoClient('mongodb://localhost:27017/')
            db = client['product_db']
            users_collection = db['users']

            user_data = users_collection.find_one({'username':username})
            if user_data and check_password_hash(user_data['password'], password):
                 user=User(str(user_data['_id']), username,user_data['password'],user_data.get('is_admin',False))
                 login_user(user)
                 flash('Logged in successfully.', 'success')
                 return redirect(url_for('index'))
            else:
                flash('Invalid username or password.', 'danger')
                return render_template('login.html') #add return statement here

        except Exception as e:
              flash(f'Error logging in: {e}', 'danger')
              return render_template('login.html') #add return statement here
        finally:
            if client:
               client.close()

    return render_template('login.html') # Add return statement here for GET requests

# User logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('index'))

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        category = request.form['category']
        return redirect(url_for('products', category=category))
    return render_template('index.html')

@app.route('/products/<category>')
def products(category):
    
    # Check if the data exists in MongoDB
    products_data = get_products_from_mongodb(category)
    if not products_data:
        # If not, scrape the data
        my_amazon_bot = AmazonProductScraper()
        category_details = my_amazon_bot.get_category_url(category)
        navigation = my_amazon_bot.navigate_to_other_pages(category_details)
        my_amazon_bot.product_information_json(navigation)
        products_data = get_products_from_mongodb(category)

    if products_data:
         # Store the current category in session
         session['last_category'] = category
         return render_template('products.html', products=products_data, category=category)
    else:
        return "No products found for this category, or an error occurred."

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    product_id = request.form.get('product_id')
    category = request.form.get('category')

    products_data = get_products_from_mongodb(category)

    if products_data:

        # Find the product based on its ID
        selected_product = None
        for i, product in enumerate(products_data):
            if str(product['_id']) == product_id:
                selected_product = product
                break

        if selected_product:
            # Convert ObjectId to string before storing in session

            def convert_object_ids_to_strings(obj):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        obj[key] = convert_object_ids_to_strings(value)
                    return obj

                elif isinstance(obj, list):
                    return [convert_object_ids_to_strings(item) for item in obj]

                elif isinstance(obj, ObjectId):
                    return str(obj)

                else:
                    return obj

            selected_product = convert_object_ids_to_strings(selected_product)

            if current_user.is_authenticated:
                user_id = str(current_user.id)
                if 'carts' not in session:
                    session['carts'] = {}
                if user_id not in session['carts']:
                    session['carts'][user_id] = []
                session['carts'][user_id].append(selected_product)
            else:
                 if 'anonymous_cart' not in session:
                    session['anonymous_cart'] = []
                 session['anonymous_cart'].append(selected_product)


            flash('Product added to cart!', 'success') # Added a flash message

        return redirect(url_for('products', category=category)) # Redirect back to the product page

    return "Product not found"

@app.route('/panier')
def panier():
   
    if current_user.is_authenticated:
        user_id = str(current_user.id)
        cart_items = session.get('carts', {}).get(user_id, [])
    else:
        cart_items=session.get('anonymous_cart', [])

    # Restore ObjectId for display purposes if needed
    def restore_object_ids(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                obj[key] = restore_object_ids(value)
            return obj

        elif isinstance(obj, list):
            return [restore_object_ids(item) for item in obj]

        elif isinstance(obj, str): # Check if it's a string
             try:
                 return ObjectId(obj)
             except:
                return obj
        else:
            return obj

    cart_items = restore_object_ids(cart_items) #convert the ids back to object id
    return render_template('panier.html', cart_items=cart_items)
# Route to remove an item from the cart
@app.route('/remove_from_cart/<int:index>')
def remove_from_cart(index):
    if current_user.is_authenticated:
        # Handle logged-in users
        user_id = str(current_user.id)  # Get user ID as string
        if 'carts' in session and user_id in session['carts']:
            cart = session['carts'][user_id]
            if 0 <= index < len(cart):  # Check if index is valid
                del cart[index]
                # Update session and ensure ObjectId is converted
                session['carts'][user_id] = convert_object_ids_to_strings(cart)
                session.modified = True
                flash('Product removed from cart!', 'success')
            else:
                flash('Invalid item index', 'danger')
    else:
        # Handle anonymous users
        if 'anonymous_cart' in session:
            cart = session['anonymous_cart']
            if 0 <= index < len(cart):  # Check if index is valid
                del cart[index]
                # Update session and ensure ObjectId is converted
                session['anonymous_cart'] = convert_object_ids_to_strings(cart)
                session.modified = True
                flash('Product removed from cart!', 'success')
            else:
                flash('Invalid item index', 'danger')
    
    # Redirect to the cart page
    return redirect(url_for('panier'))
@app.route('/confirm_cart', methods=['POST'])
@login_required
def confirm_cart():
    if current_user.is_authenticated:
        user_id = str(current_user.id)
        if 'carts' in session and user_id in session['carts']:
            cart_items = session['carts'][user_id]

            try:
                client = MongoClient('mongodb://localhost:27017/')
                db = client['product_db']
                users_collection = db['users']

                # Convertir les ObjectId en chaînes avant l'enregistrement
                cart_items_str = convert_object_ids_to_strings(cart_items)

                # Créer l'objet de la commande
                order = {
                    'user_id': ObjectId(user_id),  # enregistrer l'ObjectId de l'utilisateur
                    'items': cart_items_str,
                    'order_date': datetime.now(),
                    'status': 'Confirmed'  # Vous pouvez ajouter d'autres statuts comme 'Processing', 'Shipped', etc.
                }

                # Mettre à jour l'utilisateur avec la nouvelle commande dans un tableau 'orders'
                users_collection.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$push': {'orders': order}}
                )

                del session['carts'][user_id] #vider le panier apres la confirmation

                flash('Your order has been confirmed', 'success')
                return redirect(url_for('index'))  # Retourner à l'accueil après la confirmation
            except Exception as e:
                flash(f'Error confirming order: {e}', 'danger')
                return redirect(url_for('panier'))
            finally:
                if client:
                    client.close()

    return redirect(url_for('panier')) # Gérer le cas où l'utilisateur n'est pas connecté ou n'a pas de panier.

@app.route('/admin')
@login_required
def admin():
    if current_user.is_admin:
        return render_template('admin.html')
    else:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('index')) #back to index page if not admin


@app.route('/add_product', methods=['GET', 'POST'])
@login_required
def add_product():
     if not current_user.is_admin:
         flash('You do not have permission to access this page.', 'danger')
         return redirect(url_for('index')) #back to index page if not admin
     if request.method == 'POST':
         # Extract product details from form
        product_name = request.form['product_name']
        product_price = request.form['product_price']
        product_rating = request.form['product_rating']
        product_review_count = request.form['product_review_count']
        product_description = request.form['product_description']
        product_sold = request.form['product_sold']
        product_image_url= request.form['product_image_url']
        category = request.form['category']
         # Add product to MongoDB
        try:
            client = MongoClient('mongodb://localhost:27017/')
            db = client['product_db']
            collection = db[category]  # Use the category as the collection name
            new_product = {
               'Title': product_name,
               'Price': product_price,
               'Rating': product_rating,
               'Review Count': product_review_count,
               'Description': product_description,
               'Sold': product_sold,
               'Image URL': product_image_url
            }
            collection.insert_one(new_product)
            flash('Product added successfully.', 'success')
            return redirect(url_for('admin'))
        except Exception as e:
            flash(f'Error adding product: {e}', 'danger')
            return redirect(url_for('admin'))
        finally:
            if client:
                client.close()

     return render_template('add_product.html')

@app.route('/delete_product', methods=['GET', 'POST'])
@login_required
def delete_product():
    if not current_user.is_admin:
         flash('You do not have permission to access this page.', 'danger')
         return redirect(url_for('index')) #back to index page if not admin

    if request.method == 'POST':
        product_id = request.form['product_id']
        category = request.form['category']
        try:
            client = MongoClient('mongodb://localhost:27017/')
            db = client['product_db']
            collection = db[category]
            result = collection.delete_one({'_id': ObjectId(product_id)})
            if result.deleted_count > 0 :
               flash('Product deleted successfully.', 'success')
            else:
               flash('Product not found.', 'danger')
            return redirect(url_for('admin'))
        except Exception as e:
            flash(f'Error deleting product: {e}', 'danger')
            return redirect(url_for('admin'))
        finally:
            if client:
                client.close()
    return render_template('delete_product.html')

if __name__ == '__main__':
    app.run(debug=True)