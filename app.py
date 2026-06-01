from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import os
import database as db

app = Flask(__name__)
app.secret_key = "nuvemvet-sistema-luana"

SECOES = [
    ("consultas",   "Consultas"),
    ("vacinas",     "Vacinas"),
    ("receituario", "Receituário"),
    ("exames",      "Exames"),
    ("cirurgias",   "Cirurgias"),
    ("pesagens",    "Pesagens"),
    ("anotacoes",   "Anotações"),
]


@app.before_request
def setup():
    db.init_db()


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    stats = {
        "clientes":  db.total_clientes(),
        "animais":   db.total_animais(),
        "consultas": db.total_registros("consultas"),
        "vacinas":   db.total_registros("vacinas"),
        "exames":    db.total_registros("exames"),
    }
    return render_template("dashboard.html", stats=stats)


# ─── CLIENTES ─────────────────────────────────────────────────────────────────

@app.route("/clientes")
def clientes():
    q       = request.args.get("q", "").strip()
    pagina  = int(request.args.get("p", 1))
    por_pag = 50
    offset  = (pagina - 1) * por_pag

    lista   = db.buscar_clientes(q=q, limite=por_pag, offset=offset)
    total   = db.total_clientes()
    paginas = (total + por_pag - 1) // por_pag

    return render_template("clientes.html",
                           clientes=lista, q=q,
                           pagina=pagina, paginas=paginas)


@app.route("/clientes/novo", methods=["GET", "POST"])
def novo_cliente():
    if request.method == "POST":
        dados = {
            "nome":       request.form.get("nome", "").strip(),
            "cpf":        request.form.get("cpf", "").strip(),
            "celular":    request.form.get("celular", "").strip(),
            "telefone":   request.form.get("telefone", "").strip(),
            "email":      request.form.get("email", "").strip(),
            "endereco":   request.form.get("endereco", "").strip(),
            "cidade":     request.form.get("cidade", "").strip(),
            "nascimento": request.form.get("nascimento", "").strip(),
            "observacao": request.form.get("observacao", "").strip(),
        }
        if not dados["nome"]:
            flash("Nome é obrigatório.", "danger")
            return render_template("novo_cliente.html", form=dados)

        id_novo = db.inserir_cliente(dados)
        flash(f"Cliente '{dados['nome']}' cadastrado com sucesso!", "success")
        return redirect(url_for("cliente", id_cliente=f"new_{id_novo}"))

    return render_template("novo_cliente.html", form={})


@app.route("/clientes/<id_cliente>")
def cliente(id_cliente):
    dados   = db.get_cliente(id_cliente)
    animais = db.get_animais_cliente(id_cliente)
    secao   = request.args.get("secao", "")
    id_animal = request.args.get("animal", "")

    registros = []
    if secao and id_animal:
        registros = db.get_registros_animal(id_cliente, id_animal, secao)

    return render_template("cliente.html",
                           cliente=dados,
                           id_cliente=id_cliente,
                           animais=animais,
                           secoes=SECOES,
                           secao_ativa=secao,
                           id_animal_ativo=id_animal,
                           registros=registros)


# ─── ANIMAIS ──────────────────────────────────────────────────────────────────

@app.route("/clientes/<id_cliente>/novo-animal", methods=["GET", "POST"])
def novo_animal(id_cliente):
    cliente = db.get_cliente(id_cliente)
    if request.method == "POST":
        dados = {
            "id_cliente": id_cliente,
            "nome":       request.form.get("nome", "").strip(),
            "especie":    request.form.get("especie", "").strip(),
            "raca":       request.form.get("raca", "").strip(),
            "sexo":       request.form.get("sexo", "").strip(),
            "nascimento": request.form.get("nascimento", "").strip(),
            "pelagem":    request.form.get("pelagem", "").strip(),
            "chip":       request.form.get("chip", "").strip(),
            "observacao": request.form.get("observacao", "").strip(),
        }
        if not dados["nome"]:
            flash("Nome do animal é obrigatório.", "danger")
            return render_template("novo_animal.html", cliente=cliente, id_cliente=id_cliente, form=dados)

        db.inserir_animal(dados)
        flash(f"Animal '{dados['nome']}' cadastrado com sucesso!", "success")
        return redirect(url_for("cliente", id_cliente=id_cliente))

    return render_template("novo_animal.html", cliente=cliente, id_cliente=id_cliente, form={})


# ─── REGISTROS MÉDICOS ────────────────────────────────────────────────────────

@app.route("/clientes/<id_cliente>/animais/<id_animal>/novo-registro", methods=["GET", "POST"])
def novo_registro(id_cliente, id_animal):
    cliente_dados = db.get_cliente(id_cliente)
    tipo  = request.args.get("tipo", "consulta")

    if request.method == "POST":
        tipo = request.form.get("tipo", tipo)
        dados = {
            "tipo":        tipo,
            "id_cliente":  id_cliente,
            "id_animal":   id_animal,
            "data":        request.form.get("data", "").strip(),
            "descricao":   request.form.get("descricao", "").strip(),
            "veterinario": request.form.get("veterinario", "").strip(),
            "observacao":  request.form.get("observacao", "").strip(),
            "arquivo":     "",
        }

        # Upload de arquivo (PDF de exame, etc.)
        arquivo = request.files.get("arquivo")
        if arquivo and arquivo.filename:
            pasta = os.path.join("dados_exportados", "exames_pdf")
            os.makedirs(pasta, exist_ok=True)
            nome_arquivo = f"manual_{id_cliente}_{id_animal}_{arquivo.filename}"
            caminho = os.path.join(pasta, nome_arquivo)
            arquivo.save(caminho)
            dados["arquivo"] = caminho

        db.inserir_registro(dados)
        flash("Registro adicionado com sucesso!", "success")
        return redirect(url_for("cliente", id_cliente=id_cliente,
                                animal=id_animal, secao=tipo + "s"))

    return render_template("novo_registro.html",
                           cliente=cliente_dados,
                           id_cliente=id_cliente,
                           id_animal=id_animal,
                           tipo=tipo,
                           tipos=SECOES)


# ─── DOWNLOAD DE PDF ──────────────────────────────────────────────────────────

@app.route("/pdf")
def ver_pdf():
    caminho = request.args.get("f", "")
    if caminho and os.path.exists(caminho):
        return send_file(caminho, mimetype="application/pdf")
    flash("Arquivo não encontrado.", "warning")
    return redirect(request.referrer or url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
