import sqlite3

email = "essential676767@gmail.com"  # Твоя почта
conn = sqlite3.connect('cyberguard.db')
cursor = conn.cursor()

try:
    cursor.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
    conn.commit()
    if cursor.rowcount > 0:
        print(f"УСПЕХ! {email} теперь админ.")
    else:
        print(f"ОШИБКА: {email} не найден. Сначала зарегистрируйся на сайте!")
except Exception as e:
    print(f"Ошибка: {e}")
finally:
    conn.close()