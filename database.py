import sqlite3
from datetime import datetime, timedelta

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot_database.db')
        self.create_tables()

    def create_tables(self):  
        with self.conn:  
            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS users (  
                id INTEGER PRIMARY KEY,  
                username TEXT,  
                first_name TEXT,  
                last_name TEXT,  
                referral_link TEXT,  
                referrer_id INTEGER,  
                verified INTEGER DEFAULT 0,  
                matic_balance INTEGER DEFAULT 0,  
                matic_wallet TEXT,  
                last_claim TIMESTAMP,  
                double_mine_active INTEGER DEFAULT 0,  
                double_mine_enabled INTEGER DEFAULT 0,  
                time_speed_enabled INTEGER DEFAULT 0          
            )""")  
            
            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS referrals (  
                id INTEGER PRIMARY KEY AUTOINCREMENT,  
                referrer_id INTEGER,  
                referred_id INTEGER  
            )""")  

            # Add 'timestamp' column to make sure it's included correctly  
            self.conn.execute('''  
            CREATE TABLE IF NOT EXISTS new_referrals (  
                referral_id INTEGER PRIMARY KEY AUTOINCREMENT,  
                referrer_id INTEGER,  
                referred_id INTEGER,  
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,  
                FOREIGN KEY (referrer_id) REFERENCES users(id),  
                FOREIGN KEY (referred_id) REFERENCES users(id)  
            )''')  

            # We need to check if the old referrals table has a 'timestamp' column   
            # before copying data from it.  

            try:  
                # Copy data from old referrals table to new referrals table  
                self.conn.execute('''  
                INSERT INTO new_referrals (referrer_id, referred_id, timestamp)  
                SELECT referrer_id, referred_id, CURRENT_TIMESTAMP FROM referrals  
                ''')  
            except sqlite3.OperationalError:  
                print("The column 'timestamp' does not exist in the 'referrals' table.")  
            
            # Drop the old referrals table  
            self.conn.execute('DROP TABLE IF EXISTS referrals')  

            # Rename the new referrals table to the old table name  
            self.conn.execute('ALTER TABLE new_referrals RENAME TO referrals')  

            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS tasks (  
                id INTEGER PRIMARY KEY AUTOINCREMENT,  
                photo_file_id TEXT,  
                description TEXT  
            )""")  
            
            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS task_proofs (  
                id INTEGER PRIMARY KEY AUTOINCREMENT,  
                user_id INTEGER,  
                photo_file_id TEXT,  
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP  
            )""")  
            
            self.conn.execute("""  
            CREATE TABLE IF NOT EXISTS task_completions (  
                id INTEGER PRIMARY KEY AUTOINCREMENT,  
                user_id INTEGER  
            )""")

    def deduct_matic_balance(self, user_id, amount):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT matic_balance FROM users WHERE id = ?", (user_id,))
            current_balance = cursor.fetchone()[0]

            if current_balance >= amount:
                self.conn.execute("UPDATE users SET matic_balance = matic_balance - ? WHERE id = ?", (amount, user_id))
                print(f"Deducted {amount} MATIC coins from user {user_id}")
            else:
                print("Insufficient MATIC balance to perform deduction.")

    def add_user(self, user_id, username, first_name, last_name, referral_link, referrer_id):
        with self.conn:
            self.conn.execute("""
            INSERT OR IGNORE INTO users (id, username, first_name, last_name, referral_link, referrer_id)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, username, first_name, last_name, referral_link, referrer_id))
            if referrer_id:
                self.conn.execute("""
                INSERT INTO referrals (referrer_id, referred_id)
                VALUES (?, ?)""",
                (referrer_id, user_id))

    def is_user_verified(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT verified FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1

    def verify_user(self, user_id):
        with self.conn:
            
            cursor = self.conn.cursor()
            cursor.execute("SELECT verified FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            
            if result and result[0] == 1:
                return  # User is already verified, do nothing
            
            # Otherwise, update user verification status
            self.conn.execute("UPDATE users SET verified = 1 WHERE id = ?", (user_id,))

            # Check if this is the first verification
            cursor.execute("SELECT matic_balance FROM users WHERE id = ?", (user_id,))
            current_balance = cursor.fetchone()[0]
            if current_balance == 0:
                # If user has 0 MATIC balance, reward them with 3 MATIC
                self.conn.execute("UPDATE users SET matic_balance = matic_balance + 3 WHERE id = ?", (user_id,))



    def update_wallet_address(self, user_id, address):
        with self.conn:
            self.conn.execute("UPDATE users SET matic_wallet = ? WHERE id = ?", (address, user_id))
    
    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM users")
        return [row[0] for row in cursor.fetchall()]


    def get_user_data(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()

        if result:
            return {
                'id': result[0],
                'username': result[1],
                'first_name': result[2],
                'last_name': result[3],
                'referral_link': result[4],
                'referrer_id': result[5],
                'verified': result[6],
                'matic_balance': result[7],
                'matic_wallet': result[8],
                'last_claim': result[9],
                'double_mine_active': result[10],
                'time_speed_enabled': result[11],  # Adjust based on your schema
                'double_mine_enabled': result[12]   # Adjust based on your schema
            }
        else:
            return None

    def get_user_matic_balance(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT matic_balance FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0

    def update_matic_balance(self, user_id, amount):
        with self.conn:
            self.conn.execute("UPDATE users SET matic_balance = matic_balance + ? WHERE id = ?", (amount, user_id))

    def add_referral(self, referrer_id, referred_id):
        with self.conn:
            self.conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))

    def get_referral_count(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def get_referrer_id(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT referrer_id FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None

    def reward_referrer(self, referrer_id, amount):
        with self.conn:
            self.conn.execute("UPDATE users SET matic_balance = matic_balance + ? WHERE id = ?", (amount, referrer_id))


    def get_last_claim_time(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT last_claim FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            try:
                return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        return None
    def get_total_users(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        result = cursor.fetchone()
        return result[0] if result else 0

    def update_last_claim_time(self, user_id):
        with self.conn:
            self.conn.execute("UPDATE users SET last_claim = ? WHERE id = ?", (datetime.now(), user_id))

    def add_task_proof(self, user_id, task_proof):
        with self.conn:
            self.conn.execute("INSERT INTO tasks (user_id, task_proof) VALUES (?, ?)", (user_id, task_proof))
        
    

    def user_has_joined_channels(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT verified FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1

    def update_user_info(self, user_id, first_name, last_name, username):
        with self.conn:
            self.conn.execute("""
            UPDATE users
            SET first_name = ?, last_name = ?, username = ?
            WHERE id = ?
            """, (first_name, last_name, username, user_id))

    def get_tasks(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT photo_file_id, description FROM tasks")
        return cursor.fetchall()

    def clear_task_proofs(self):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM task_proofs WHERE id IN (SELECT id FROM task_proofs ORDER BY id LIMIT 15)")
        self.conn.commit()

    
    def update_claim_time(self, user_id, time_delta):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT last_claim FROM users WHERE id = ?", (user_id,))
            last_claim_time = cursor.fetchone()[0]

            if last_claim_time:
                # Convert the string to a datetime object
                last_claim_time = datetime.strptime(last_claim_time, '%Y-%m-%d %H:%M:%S.%f')
                new_claim_time = last_claim_time + time_delta
            else:
                new_claim_time = datetime.now() + time_delta

            # Convert the new_claim_time back to a string before storing it in the database
            new_claim_time_str = new_claim_time.strftime('%Y-%m-%d %H:%M:%S.%f')

            self.conn.execute("UPDATE users SET last_claim = ? WHERE id = ?", (new_claim_time_str, user_id))
            print(f"Updated claim time for user {user_id} to {new_claim_time_str}")

    def activate_double_mine(self, user_id):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT matic_balance FROM users WHERE id = ?", (user_id,))
            current_balance = cursor.fetchone()[0]
    def enable_time_speed(self, user_id):
        with self.conn:
            self.conn.execute("UPDATE users SET time_speed_enabled = 1 WHERE id = ?", (user_id,))

    def enable_double_mine(self, user_id):
        with self.conn:
            self.conn.execute("UPDATE users SET double_mine_enabled = 1 WHERE id = ?", (user_id,))
    def save_task(self, photo_file_id, description):
        with self.conn:
            self.conn.execute("DELETE FROM tasks")
            self.conn.execute("DELETE FROM task_completions")
            self.conn.execute("INSERT INTO tasks (photo_file_id, description) VALUES (?, ?)", (photo_file_id, description))
    def save_task_proof(self, user_id, photo_file_id):
        with self.conn:
            self.conn.execute("INSERT INTO task_proofs (user_id, photo_file_id, timestamp) VALUES (?, ?, ?)", (user_id, photo_file_id, datetime.now()))
    def save_task_completion(self, user_id):
        with self.conn:
            self.conn.execute("INSERT INTO task_completions (user_id) VALUES (?)", (user_id,))
    def has_user_completed_task(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM task_completions WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None
    def get_task_proofs(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT user_id, photo_file_id FROM task_proofs LIMIT 15")
        return cursor.fetchall()
    # Add this method to your Database class

    def get_task_proof_date(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT timestamp FROM task_proofs WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def get_latest_instruction(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT description FROM tasks ORDER BY id DESC LIMIT 1")
        result = cursor.fetchone()
        return result[0] if result else "No instructions available."

    def update_instruction(self, new_instruction):
        self.conn.execute("INSERT INTO tasks (description) VALUES (?)", (new_instruction,))
        self.conn.commit()

    def get_user_with_most_referrals(self):
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT referrer_id, COUNT(referred_id) as referral_count
        FROM referrals
        GROUP BY referrer_id
        ORDER BY referral_count DESC
        LIMIT 1
        """)
        result = cursor.fetchone()
        if result:
            return result[0], result[1]  # Return the user_id and the referral count
        return None, 0



