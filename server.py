from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import sqlite3
import os
import uuid
from datetime import datetime

app = FastAPI()
templates = Jinja2Templates(directory="templates")
os.makedirs("arquivos_recebidos", exist_ok=True)

# Inicializa Banco de Dados Local do Servidor
def init_db():
    conn = sqlite3.connect('controle.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS lojas (cnpj TEXT PRIMARY KEY, nome TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS pedidos (id TEXT PRIMARY KEY, cnpj TEXT, inicio TEXT, fim TEXT, status TEXT)''')
    conn.commit()
    conn.close()

init_db()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    conn = sqlite3.connect('controle.db')
    cursor = conn.cursor()
    lojas = cursor.execute("SELECT * FROM lojas").fetchall()
    pedidos = cursor.execute("SELECT * FROM pedidos ORDER BY id DESC LIMIT 10").fetchall()
    arquivos = os.listdir("arquivos_recebidos")
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "lojas": lojas, "pedidos": pedidos, "arquivos": arquivos})

@app.post("/cadastrar-loja")
async def cadastrar_loja(cnpj: str = Form(...), nome: str = Form(...)):
    conn = sqlite3.connect('controle.db')
    conn.execute("INSERT OR REPLACE INTO lojas VALUES (?, ?)", (cnpj, nome))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/solicitar")
async def solicitar(cnpj: str = Form(...), inicio: str = Form(...), fim: str = Form(...)):
    pedido_id = str(uuid.uuid4())[:8]
    conn = sqlite3.connect('controle.db')
    conn.execute("INSERT INTO pedidos VALUES (?, ?, ?, ?, 'PENDENTE')", (pedido_id, cnpj, inicio, fim))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.get("/check/{cnpj}")
def check_pedido(cnpj: str):
    conn = sqlite3.connect('controle.db')
    cursor = conn.cursor()
    pedido = cursor.execute("SELECT id, inicio, fim FROM pedidos WHERE cnpj = ? AND status = 'PENDENTE' LIMIT 1", (cnpj,)).fetchone()
    conn.close()
    if pedido:
        return {"id": pedido[0], "inicio": pedido[1], "fim": pedido[2]}
    return None

@app.post("/upload/{cnpj}/{pedido_id}")
async def upload(cnpj: str, pedido_id: str, file: UploadFile = File(...)):
    filename = f"{cnpj}_{pedido_id}_{file.filename}"
    with open(f"arquivos_recebidos/{filename}", "wb") as buffer:
        buffer.write(await file.read())
    
    conn = sqlite3.connect('controle.db')
    conn.execute("UPDATE pedidos SET status = 'CONCLUIDO' WHERE id = ?", (pedido_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/download/{filename}")
def download(filename: str):
    return FileResponse(path=f"arquivos_recebidos/{filename}", filename=filename)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
