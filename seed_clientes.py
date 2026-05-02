from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models

def popular_clientes(n=50):
    db: Session = SessionLocal()
    
    try:
        # Verifica se já existem clientes para evitar duplicatas
        if db.query(models.Cliente).count() > 0:
            print("Já existem clientes no banco. Saindo...")
            return

        print(f"Inserindo {n} clientes no banco...")
        for i in range(1, n + 1):
            cliente = models.Cliente(
                nome=f"Cliente Teste {i}",
                documento=f"123456789{i:03}", # Ex: 123456789001
                telefone=f"99999-00{i:02}",
                rua="Rua Principal",
                numero=f"{i}",
                bairro="Centro",
                ponto_referencia="Perto do supermercado"
            )
            db.add(cliente)
        
        db.commit()
        print("Sucesso! 50 clientes cadastrados.")
    
    except Exception as e:
        print(f"Erro: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    popular_clientes()