from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import sqlite3
import os
import uuid
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename

app = FastAPI()

templates = Jinja2Templates(directory="templates")

# Diretório onde os arquivos recebidos serão armazenados
PASTA_ARQUIVOS = Path("arquivos_recebidos")
PASTA_ARQUIVOS.mkdir(exist_ok=True)

# Extensões permitidas
EXTENSOES_PERMITIDAS = {
    ".zip",
    ".rar",
    ".7z",
    ".xml",
    ".pdf",
    ".csv",
    ".xlsx",
    ".xls"
}


# ============================================================
# BANCO DE DADOS
# ============================================================

def get_connection():
    conn = sqlite3.connect("controle.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    try:
        cursor = conn.cursor()

        # Tabela de lojas
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lojas (
                cnpj TEXT PRIMARY KEY,
                nome TEXT NOT NULL
            )
        """)

        # Tabela de pedidos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id TEXT PRIMARY KEY,
                cnpj TEXT NOT NULL,
                inicio TEXT NOT NULL,
                fim TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDENTE',
                criado_em TEXT,
                concluido_em TEXT
            )
        """)

        # Compatibilidade com banco antigo
        # Caso a tabela pedidos já exista sem essas colunas,
        # elas serão adicionadas automaticamente.

        colunas = [
            row["name"]
            for row in cursor.execute("PRAGMA table_info(pedidos)").fetchall()
        ]

        if "criado_em" not in colunas:
            cursor.execute("""
                ALTER TABLE pedidos
                ADD COLUMN criado_em TEXT
            """)

        if "concluido_em" not in colunas:
            cursor.execute("""
                ALTER TABLE pedidos
                ADD COLUMN concluido_em TEXT
            """)

        conn.commit()

    finally:
        conn.close()


init_db()


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def agora():
    """
    Retorna data/hora atual no formato:
    17/09/2026 18:00:00
    """
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def normalizar_cnpj(cnpj: str):
    """
    Remove pontuação do CNPJ.
    Exemplo:
    12.345.678/0001-90
    vira
    12345678000190
    """
    return "".join(filter(str.isdigit, cnpj))


def validar_cnpj(cnpj: str):
    """
    Validação básica:
    - somente números
    - exatamente 14 dígitos
    """

    cnpj = normalizar_cnpj(cnpj)

    if len(cnpj) != 14:
        return False

    if not cnpj.isdigit():
        return False

    # Rejeita sequências como 00000000000000
    if len(set(cnpj)) == 1:
        return False

    return True


def extensao_permitida(filename: str):
    """
    Verifica a extensão do arquivo.
    """
    extensao = Path(filename).suffix.lower()
    return extensao in EXTENSOES_PERMITIDAS


# ============================================================
# PÁGINA PRINCIPAL
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    conn = get_connection()

    try:
        lojas = conn.execute(
            "SELECT cnpj, nome FROM lojas ORDER BY nome"
        ).fetchall()

        pedidos = conn.execute("""
            SELECT
                id,
                cnpj,
                inicio,
                fim,
                status,
                criado_em,
                concluido_em
            FROM pedidos
            ORDER BY criado_em DESC
            LIMIT 10
        """).fetchall()

        arquivos = [
            arquivo.name
            for arquivo in PASTA_ARQUIVOS.iterdir()
            if arquivo.is_file()
        ]

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "lojas": lojas,
                "pedidos": pedidos,
                "arquivos": arquivos
            }
        )

    except sqlite3.Error as e:

        print(f"Erro ao carregar página inicial: {e}")

        raise HTTPException(
            status_code=500,
            detail="Erro ao consultar o banco de dados."
        )

    finally:
        conn.close()


# ============================================================
# CADASTRAR LOJA
# ============================================================

@app.post("/cadastrar-loja")
async def cadastrar_loja(
    cnpj: str = Form(...),
    nome: str = Form(...)
):

    cnpj = normalizar_cnpj(cnpj)
    nome = nome.strip()

    # Validação do CNPJ
    if not validar_cnpj(cnpj):
        raise HTTPException(
            status_code=400,
            detail="CNPJ inválido. Informe um CNPJ com 14 dígitos."
        )

    if not nome:
        raise HTTPException(
            status_code=400,
            detail="O nome da loja é obrigatório."
        )

    conn = get_connection()

    try:

        conn.execute(
            """
            INSERT OR REPLACE INTO lojas (cnpj, nome)
            VALUES (?, ?)
            """,
            (cnpj, nome)
        )

        conn.commit()

    except sqlite3.Error as e:

        conn.rollback()

        print(f"Erro ao cadastrar loja: {e}")

        raise HTTPException(
            status_code=500,
            detail="Erro ao cadastrar loja."
        )

    finally:
        conn.close()

    return RedirectResponse(
        url="/",
        status_code=303
    )


# ============================================================
# CRIAR SOLICITAÇÃO
# ============================================================

@app.post("/solicitar")
async def solicitar(
    cnpj: str = Form(...),
    inicio: str = Form(...),
    fim: str = Form(...)
):

    cnpj = normalizar_cnpj(cnpj)

    # ========================================================
    # 1. Validar CNPJ
    # ========================================================

    if not validar_cnpj(cnpj):
        raise HTTPException(
            status_code=400,
            detail="CNPJ inválido."
        )

    conn = get_connection()

    try:

        # ====================================================
        # 2. Verificar se a loja existe
        # ====================================================

        loja = conn.execute(
            "SELECT cnpj FROM lojas WHERE cnpj = ?",
            (cnpj,)
        ).fetchone()

        if not loja:
            raise HTTPException(
                status_code=404,
                detail="Loja não cadastrada."
            )

        # ====================================================
        # 3. Criar UUID completo
        # ====================================================

        pedido_id = str(uuid.uuid4())

        # ====================================================
        # 4. Registrar data de criação
        # ====================================================

        criado_em = agora()

        conn.execute(
            """
            INSERT INTO pedidos (
                id,
                cnpj,
                inicio,
                fim,
                status,
                criado_em,
                concluido_em
            )
            VALUES (?, ?, ?, ?, 'PENDENTE', ?, NULL)
            """,
            (
                pedido_id,
                cnpj,
                inicio,
                fim,
                criado_em
            )
        )

        conn.commit()

    except HTTPException:
        raise

    except sqlite3.Error as e:

        conn.rollback()

        print(f"Erro ao criar pedido: {e}")

        raise HTTPException(
            status_code=500,
            detail="Erro ao criar solicitação."
        )

    finally:
        conn.close()

    return RedirectResponse(
        url="/",
        status_code=303
    )


# ============================================================
# CONSULTAR PEDIDO PENDENTE
# ============================================================

@app.get("/check/{cnpj}")
def check_pedido(cnpj: str):

    cnpj = normalizar_cnpj(cnpj)

    if not validar_cnpj(cnpj):
        raise HTTPException(
            status_code=400,
            detail="CNPJ inválido."
        )

    conn = get_connection()

    try:

        pedido = conn.execute("""
            SELECT
                id,
                inicio,
                fim
            FROM pedidos
            WHERE cnpj = ?
              AND status = 'PENDENTE'
            ORDER BY criado_em DESC
            LIMIT 1
        """, (cnpj,)).fetchone()

        if pedido:

            return {
                "id": pedido["id"],
                "inicio": pedido["inicio"],
                "fim": pedido["fim"]
            }

        return None

    except sqlite3.Error as e:

        print(f"Erro ao consultar pedido: {e}")

        raise HTTPException(
            status_code=500,
            detail="Erro ao consultar pedido."
        )

    finally:
        conn.close()


# ============================================================
# UPLOAD
# ============================================================

@app.post("/upload/{cnpj}/{pedido_id}")
async def upload(
    cnpj: str,
    pedido_id: str,
    file: UploadFile = File(...)
):

    cnpj = normalizar_cnpj(cnpj)

    # ========================================================
    # 1. Validar CNPJ
    # ========================================================

    if not validar_cnpj(cnpj):
        raise HTTPException(
            status_code=400,
            detail="CNPJ inválido."
        )

    # ========================================================
    # 2. Verificar nome do arquivo
    # ========================================================

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Nenhum arquivo foi enviado."
        )

    # ========================================================
    # 3. Verificar extensão
    # ========================================================

    if not extensao_permitida(file.filename):
        raise HTTPException(
            status_code=400,
            detail="Tipo de arquivo não permitido."
        )

    # ========================================================
    # 4. Verificar pedido
    # ========================================================

    conn = get_connection()

    try:

        pedido = conn.execute("""
            SELECT
                id,
                cnpj,
                status
            FROM pedidos
            WHERE id = ?
              AND cnpj = ?
              AND status = 'PENDENTE'
        """, (
            pedido_id,
            cnpj
        )).fetchone()

        if not pedido:

            raise HTTPException(
                status_code=404,
                detail="Pedido não encontrado ou já concluído."
            )

        # ====================================================
        # 5. Nome seguro
        # ====================================================

        nome_original = secure_filename(file.filename)

        if not nome_original:
            raise HTTPException(
                status_code=400,
                detail="Nome de arquivo inválido."
            )

        extensao = Path(nome_original).suffix.lower()

        # UUID garante que o nome físico nunca seja
        # controlado diretamente pelo usuário.

        nome_arquivo = (
            f"{cnpj}_{pedido_id}{extensao}"
        )

        caminho_arquivo = PASTA_ARQUIVOS / nome_arquivo

        # ====================================================
        # 6. Gravar arquivo
        # ====================================================

        try:

            with open(caminho_arquivo, "wb") as buffer:

                while True:

                    bloco = await file.read(1024 * 1024)

                    if not bloco:
                        break

                    buffer.write(bloco)

        except OSError as e:

            print(f"Erro ao salvar arquivo: {e}")

            raise HTTPException(
                status_code=500,
                detail="Erro ao salvar arquivo."
            )

        # ====================================================
        # 7. Marcar pedido como concluído
        # ====================================================

        concluido_em = agora()

        conn.execute("""
            UPDATE pedidos
            SET
                status = 'CONCLUIDO',
                concluido_em = ?
            WHERE id = ?
              AND cnpj = ?
              AND status = 'PENDENTE'
        """, (
            concluido_em,
            pedido_id,
            cnpj
        ))

        conn.commit()

        return {
            "status": "ok",
            "pedido_id": pedido_id,
            "arquivo": nome_arquivo
        }

    except HTTPException:
        raise

    except sqlite3.Error as e:

        conn.rollback()

        print(f"Erro no upload: {e}")

        # Se o arquivo foi salvo mas ocorreu erro
        # no banco, remove o arquivo para evitar
        # deixar arquivo órfão.

        if 'caminho_arquivo' in locals():
            try:
                if caminho_arquivo.exists():
                    caminho_arquivo.unlink()
            except OSError:
                pass

        raise HTTPException(
            status_code=500,
            detail="Erro ao registrar arquivo no banco."
        )

    finally:
        conn.close()


# ============================================================
# DOWNLOAD
# ============================================================

@app.get("/download/{filename}")
def download(filename: str):

    # ========================================================
    # 1. Segurança: aceitar somente nome de arquivo
    # ========================================================

    nome_arquivo = os.path.basename(filename)

    if nome_arquivo != filename:
        raise HTTPException(
            status_code=400,
            detail="Nome de arquivo inválido."
        )

    # ========================================================
    # 2. Caminho seguro
    # ========================================================

    caminho = PASTA_ARQUIVOS / nome_arquivo

    # Resolve o caminho para impedir acesso fora
    # da pasta arquivos_recebidos.

    try:

        caminho_resolvido = caminho.resolve()
        pasta_resolvida = PASTA_ARQUIVOS.resolve()

        if pasta_resolvida not in caminho_resolvido.parents:
            raise HTTPException(
                status_code=403,
                detail="Acesso ao arquivo não permitido."
            )

    except OSError:

        raise HTTPException(
            status_code=400,
            detail="Caminho de arquivo inválido."
        )

    # ========================================================
    # 3. Verificar existência
    # ========================================================

    if not caminho_resolvido.is_file():
        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado."
        )

    # ========================================================
    # 4. Enviar arquivo
    # ========================================================

    return FileResponse(
        path=str(caminho_resolvido),
        filename=nome_arquivo
    )


# ============================================================
# EXECUÇÃO
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )