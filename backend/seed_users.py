import uuid
from database import Database
from models import User, UserRole

def seed_database():
    db = Database()
    
    # Define users to add
    users_to_seed = [
        User(
            id=str(uuid.uuid4()),
            email="ta@university.edu",
            password="ta123",
            role=UserRole.TA,
            roll_number=None
        ),
        User(
            id=str(uuid.uuid4()),
            email="student@university.edu",
            password="student123",
            role=UserRole.STUDENT,
            roll_number="2023CSB1001"
        )
    ]
    
    print("🌱 Seeding initial users...")
    
    for user in users_to_seed:
        # Check if user already exists
        existing_user = db.get_user_by_email(user.email)
        
        from api.endpoints import pwd_context
        
        if not existing_user:
            try:
                user.password = pwd_context.hash(user.password)
                db.create_user(user)
                print(f"✅ Added {user.role.upper()}: {user.email}")
            except Exception as e:
                print(f"❌ Failed to add {user.email}: {e}")
        else:
            # Check if existing password is plain text
            is_hashed = existing_user['password'].startswith('$pbkdf2-sha256$')
            if not is_hashed:
                print(f"ℹ️ Updating password for {user.email} to hashed version.")
                user.password = pwd_context.hash(user.password)
                db.create_user(user)
            else:
                print(f"ℹ️ User {user.email} already exists and is hashed. Skipping.")
            
    print("\n✨ Seeding complete! You can now use these credentials to log in.")
    print("-" * 50)
    print(f"TA Login:      ta@university.edu / ta123")
    print(f"Student Login: student@university.edu / student123")
    print("-" * 50)

if __name__ == "__main__":
    seed_database()
