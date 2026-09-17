```python
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import sqlite3
import os
import uuid

from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURAÇÃO
# ============================================================

app = FastAPI()

templates = Jinja2Templates(directory="templates")

PASTA_ARQUIVOS = Path("arquivos_recebidos")
PASTA_ARQUIVOS.mkdir(exist_ok=True)

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

        # ----------------------------------------------------
        # LOJAS
        # ----------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lojas (
                cnpj TEXT PRIMARY KEY,
                nome TEXT NOT NULL
            )
        """)

        # ----------------------------------------------------
        # PEDIDOS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # COMPATIBILIDADE COM BANCO EXISTENTE
        # ----------------------------------------------------

        colunas = [
            row["name"]
            for row in cursor.execute(
                "PRAGMA table_info(pedidos)"
            ).fetchall()
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

    except sqlite3.Error as e:

        conn.rollback()

        print(f"ERRO AO INICIALIZAR BANCO: {e}")

        raise

    finally:

        conn.close()


init_db()


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def agora():
    """
    Retorna data/hora atual.
    """

    return datetime.now().strftime(
        "%d/%m/%Y %H:%M:%S"
    )


def normalizar_cnpj(cnpj: str):
    """
    Remove pontos, barras e hífens do CNPJ.
    """

    return "".join(
        caractere
        for caractere in cnpj
        if caractere.isdigit()
    )


def validar_cnpj(cnpj: str):
    """
    Validação básica do CNPJ.

    Verifica:
    - 14 dígitos
    - somente números
    - não permite sequência de números iguais
    """

    cnpj = normalizar_cnpj(cnpj)

    if len(cnpj) != 14:
        return False

    if not cnpj.isdigit():
        return False

    if len(set(cnpj)) == 1:
        return False

    return True


def obter_nome_seguro(filename: str):
    """
    Obtém somente o nome do arquivo, eliminando
    qualquer caminho enviado pelo cliente.

    Exemplo:

    ../../arquivo.zip

    vira:

    arquivo.zip
    """

    if not filename:
        return ""

    return Path(filename).name


def obter_extensao(filename: str):
    """
    Retorna a extensão do arquivo em letras minúsculas.
    """

    return Path(filename).suffix.lower()


def extensao_permitida(filename: str):
    """
    Verifica se a extensão está na lista permitida.
    """

    extensao = obter_extensao(filename)

    return extensao in EXTENSOES_PERMITIDAS


# ============================================================
# PÁGINA PRINCIPAL
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    conn = get_connection()

    try:

        lojas = conn.execute("""
            SELECT
                cnpj,
                nome
            FROM lojas
            ORDER BY nome
        """).fetchall()

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

        print(f"ERRO AO CARREGAR PÁGINA: {e}")

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

    # --------------------------------------------------------
    # VALIDAR CNPJ
    # --------------------------------------------------------

    if not validar_cnpj(cnpj):

        raise HTTPException(
            status_code=400,
            detail="CNPJ inválido. Informe um CNPJ com 14 dígitos."
        )

    # --------------------------------------------------------
    # VALIDAR NOME
    # --------------------------------------------------------

    if not nome:

        raise HTTPException(
            status_code=400,
            detail="O nome da loja é obrigatório."
        )

    conn = get_connection()

    try:

        conn.execute("""
            INSERT OR REPLACE INTO lojas (
                cnpj,
                nome
            )
            VALUES (?, ?)
        """, (
            cnpj,
            nome
        ))

        conn.commit()

    except sqlite3.Error as e:

        conn.rollback()

        print(f"ERRO AO CADASTRAR LOJA: {e}")

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

    # --------------------------------------------------------
    # VALIDAR CNPJ
    # --------------------------------------------------------

    if not validar_cnpj(cnpj):

        raise HTTPException(
            status_code=400,
            detail="CNPJ inválido."
        )

    conn = get_connection()

    try:

        # ----------------------------------------------------
        # VERIFICAR SE A LOJA EXISTE
        # ----------------------------------------------------

        loja = conn.execute("""
            SELECT cnpj
            FROM lojas
            WHERE cnpj = ?
        """, (
            cnpj,
        )).fetchone()

        if not loja:

            raise HTTPException(
                status_code=404,
                detail="Loja não cadastrada."
            )

        # ----------------------------------------------------
        # GERAR ID COMPLETO
        # ----------------------------------------------------

        pedido_id = str(uuid.uuid4())

        # ----------------------------------------------------
        # DATA DE CRIAÇÃO
        # ----------------------------------------------------

        criado_em = agora()

        # ----------------------------------------------------
        # CRIAR PEDIDO
        # ----------------------------------------------------

        conn.execute("""
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
        """, (
            pedido_id,
            cnpj,
            inicio,
            fim,
            criado_em
        ))

        conn.commit()

    except HTTPException:

        raise

    except sqlite3.Error as e:

        conn.rollback()

        print(f"ERRO AO CRIAR PEDIDO: {e}")

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
# CONSULTAR PEDIDO
# ============================================================

@app.get("/check/{cnpj}")
def check_pedido(cnpj: str):

    cnpj = normalizar_cnpj(cnpj)

    # --------------------------------------------------------
    # VALIDAR CNPJ
    # --------------------------------------------------------

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
        """, (
            cnpj,
        )).fetchone()

        if pedido:

            return {
                "id": pedido["id"],
                "inicio": pedido["inicio"],
                "fim": pedido["fim"]
            }

        return None

    except sqlite3.Error as e:

        print(f"ERRO AO CONSULTAR PEDIDO: {e}")

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

    # --------------------------------------------------------
    # VALIDAR CNPJ
    # --------------------------------------------------------

    if not validar_cnpj(cnpj):

        raise HTTPException(
            status_code=400,
            detail="CNPJ inválido."
        )

    # --------------------------------------------------------
    # VALIDAR ARQUIVO
    # --------------------------------------------------------

    if not file.filename:

        raise HTTPException(
            status_code=400,
            detail="Nenhum arquivo foi enviado."
        )

    # --------------------------------------------------------
    # OBTER NOME SEGURO
    # --------------------------------------------------------

    nome_original = obter_nome_seguro(
        file.filename
    )

    if not nome_original:

        raise HTTPException(
            status_code=400,
            detail="Nome de arquivo inválido."
        )

    # --------------------------------------------------------
    # VALIDAR EXTENSÃO
    # --------------------------------------------------------

    if not extensao_permitida(nome_original):

        raise HTTPException(
            status_code=400,
            detail=(
                "Tipo de arquivo não permitido. "
                f"Extensões permitidas: "
                f"{', '.join(sorted(EXTENSOES_PERMITIDAS))}"
            )
        )

    extensao = obter_extensao(
        nome_original
    )

    conn = get_connection()

    caminho_arquivo = None

    try:

        # ----------------------------------------------------
        # VERIFICAR PEDIDO
        #
        # IMPORTANTE:
        # O pedido precisa pertencer ao CNPJ informado.
        # ----------------------------------------------------

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
                detail=(
                    "Pedido não encontrado, "
                    "não pertence a este CNPJ "
                    "ou já foi concluído."
                )
            )

        # ----------------------------------------------------
        # GERAR NOME DO ARQUIVO NO SERVIDOR
        #
        # O nome enviado pelo cliente NÃO é utilizado.
        # ----------------------------------------------------

        nome_arquivo = (
            f"{cnpj}_{pedido_id}{extensao}"
        )

        caminho_arquivo = (
            PASTA_ARQUIVOS / nome_arquivo
        )

        # ----------------------------------------------------
        # GRAVAR ARQUIVO
        #
        # Lê em blocos de 1 MB para não carregar
        # o arquivo inteiro na memória.
        # ----------------------------------------------------

        try:

            with open(
                caminho_arquivo,
                "wb"
            ) as buffer:

                while True:

                    bloco = await file.read(
                        1024 * 1024
                    )

                    if not bloco:
                        break

                    buffer.write(bloco)

        except OSError as e:

            print(
                f"ERRO AO SALVAR ARQUIVO: {e}"
            )

            raise HTTPException(
                status_code=500,
                detail="Erro ao salvar arquivo."
            )

        # ----------------------------------------------------
        # MARCAR PEDIDO COMO CONCLUÍDO
        # ----------------------------------------------------

        concluido_em = agora()

        cursor = conn.execute("""
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

        # ----------------------------------------------------
        # VERIFICAR SE O UPDATE REALMENTE OCORREU
        # ----------------------------------------------------

        if cursor.rowcount != 1:

            conn.rollback()

            # Remover arquivo que acabou de ser criado
            if caminho_arquivo.exists():

                try:
                    caminho_arquivo.unlink()
                except OSError:
                    pass

            raise HTTPException(
                status_code=409,
                detail=(
                    "O pedido não pôde ser concluído. "
                    "Ele pode ter sido processado anteriormente."
                )
            )

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

        print(
            f"ERRO NO BANCO DURANTE UPLOAD: {e}"
        )

        # ----------------------------------------------------
        # Se o arquivo foi criado mas o banco falhou,
        # remove o arquivo para não deixar arquivo órfão.
        # ----------------------------------------------------

        if caminho_arquivo:

            try:

                if caminho_arquivo.exists():
                    caminho_arquivo.unlink()

            except OSError:
                pass

        raise HTTPException(
            status_code=500,
            detail="Erro ao registrar o arquivo no banco."
        )

    finally:

        conn.close()


# ============================================================
# DOWNLOAD
# ============================================================

@app.get("/download/{filename}")
def download(filename: str):

    # --------------------------------------------------------
    # PEGAR SOMENTE O NOME DO ARQUIVO
    # --------------------------------------------------------

    nome_arquivo = Path(filename).name

    # Se o nome recebido contém caminho,
    # rejeitar a requisição.

    if nome_arquivo != filename:

        raise HTTPException(
            status_code=400,
            detail="Nome de arquivo inválido."
        )

    # --------------------------------------------------------
    # CONSTRUIR CAMINHO
    # --------------------------------------------------------

    caminho = (
        PASTA_ARQUIVOS / nome_arquivo
    )

    try:

        caminho_resolvido = caminho.resolve()
        pasta_resolvida = (
            PASTA_ARQUIVOS.resolve()
        )

        # ----------------------------------------------------
        # GARANTIR QUE O ARQUIVO ESTÁ DENTRO DA PASTA
        # ----------------------------------------------------

        try:

            caminho_resolvido.relative_to(
                pasta_resolvida
            )

        except ValueError:

            raise HTTPException(
                status_code=403,
                detail="Acesso ao arquivo não permitido."
            )

    except HTTPException:

        raise

    except OSError:

        raise HTTPException(
            status_code=400,
            detail="Caminho de arquivo inválido."
        )

    # --------------------------------------------------------
    # VERIFICAR SE EXISTE
    # --------------------------------------------------------

    if not caminho_resolvido.is_file():

        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado."
        )

    # --------------------------------------------------------
    # ENVIAR ARQUIVO
    # --------------------------------------------------------

    try:

        return FileResponse(
            path=str(caminho_resolvido),
            filename=nome_arquivo
        )

    except Exception as e:

        print(
            f"ERRO AO ENVIAR ARQUIVO: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail="Erro ao enviar arquivo."
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
```
