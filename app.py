import os
import asyncio
import logging

import yaml
from dotenv import load_dotenv
from flask import Flask, render_template, request, session, redirect, url_for
from groq import Groq
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from openfga_sdk import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models import ClientCheckRequest
from openfga_sdk.credentials import CredentialConfiguration, Credentials

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

with open("configs/config.yaml") as f:
    config = yaml.safe_load(f)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", config["app"]["secret_key"])

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# documents and their FGA object names
DOCUMENTS = {
    "general_handbook": "documents/general_handbook.txt",
    "salary_policy": "documents/salary_policy.txt",
    "budget_q4": "documents/budget_q4.txt",
}


def get_fga_config() -> ClientConfiguration:
    """Returns FGA client configuration."""
    return ClientConfiguration(
        api_url=os.getenv("FGA_API_URL"),
        store_id=os.getenv("FGA_STORE_ID"),
        credentials=Credentials(
            method="client_credentials",
            configuration=CredentialConfiguration(
                api_issuer=os.getenv("FGA_TOKEN_ISSUER"),
                api_audience=os.getenv("FGA_API_AUDIENCE"),
                client_id=os.getenv("FGA_CLIENT_ID"),
                client_secret=os.getenv("FGA_CLIENT_SECRET"),
            ),
        ),
    )


async def check_permission(user: str, document: str) -> bool:
    """
    Checks if a user has viewer access to a document in FGA.
    """
    async with OpenFgaClient(get_fga_config()) as fga_client:
        response = await fga_client.check(ClientCheckRequest(
            user=f"user:{user}",
            relation="viewer",
            object=f"document:{document}",
        ))
        return response.allowed


def get_allowed_documents(user: str) -> list:
    """Returns list of document names the user is allowed to access."""
    allowed = []
    for doc_name in DOCUMENTS.keys():
        permitted = asyncio.run(check_permission(user, doc_name))
        if permitted:
            allowed.append(doc_name)
    logger.info("User %s has access to: %s", user, allowed)
    return allowed


def load_documents(doc_names: list) -> list:
    """Loads and splits allowed documents into chunks for RAG."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config["rag"]["chunk_size"],
        chunk_overlap=config["rag"]["chunk_overlap"]
    )
    chunks = []
    for name in doc_names:
        path = DOCUMENTS[name]
        with open(path) as f:
            text = f.read()
        chunks.extend(splitter.create_documents([text], metadatas=[{"source": name}]))
    return chunks


def build_vector_store(chunks: list) -> FAISS:
    """Builds a FAISS vector store from document chunks."""
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return FAISS.from_documents(chunks, embeddings)


def get_answer(query: str, vector_store: FAISS) -> str:
    """
    Retrieves relevant chunks and asks Groq to answer the query.
    """
    docs = vector_store.similarity_search(query, k=config["rag"]["top_k"])
    context = "\n\n".join([doc.page_content for doc in docs])

    response = groq_client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful HR assistant. Answer based only on the provided context. If the answer is not in the context, say you don't have that information."
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {query}"
            }
        ]
    )
    return response.choices[0].message.content


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip().lower()
    # only allow nova and rex for this demo
    if username not in ["nova", "rex"]:
        return render_template("home.html", error="Unknown user. Try nova or rex.")
    session["user"] = username
    logger.info("User logged in: %s", username)
    return redirect(url_for("chat"))


@app.route("/chat", methods=["GET", "POST"])
def chat():
    if "user" not in session:
        return redirect(url_for("home"))

    user = session["user"]
    answer = None
    query = None

    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if query:
            allowed_docs = get_allowed_documents(user)
            if not allowed_docs:
                return render_template("denied.html", user=user)

            chunks = load_documents(allowed_docs)
            vector_store = build_vector_store(chunks)
            answer = get_answer(query, vector_store)
            logger.info("Query from %s: %s", user, query)

    return render_template("chat.html", user=user, answer=answer, query=query)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=config["app"]["port"],
        debug=config["app"]["debug"]
    )