"""
offline_app.py — Sistema de consulta 100% offline.

Roda na porta 5001. Não faz nenhuma requisição externa.
Lê dados de: dados_exportados/*.csv + offline_novos.db
PDFs de:     dados_exportados/exames_pdf/

Para iniciar: python offline_app.py
Acesse em:   http://localhost:5001
"""

from flask import (Flask, render_template, request,
                   redirect, url_for, flash, send_file, session)
from jinja2 import ChoiceLoader, FileSystemLoader
from functools import wraps
import os
import offline_db as db

app = Flask(__name__, template_folder="offline_templates")

# Fallback: usa templates/ para telas ainda não customizadas no offline
app.jinja_loader = ChoiceLoader([
    FileSystemLoader("offline_templates"),
    FileSystemLoader("templates"),
])

app.secret_key = "evolvify-vet-2026-luana-feitosa"

# Identidade do produto (disponível em todos os templates)
APP_NOME    = "Sistema Vet"
APP_MARCA   = "Evolvify"


@app.context_processor
def injetar_branding():
    return {
        "APP_NOME":  APP_NOME,
        "APP_MARCA": APP_MARCA,
        "usuario_logado": session.get("usuario"),
    }


SECOES = [
    ("consultas",   "Consultas"),
    ("vacinas",     "Vacinas"),
    ("receituario", "Receituário"),
    ("exames",      "Exames"),
    ("cirurgias",   "Cirurgias"),
    ("pesagens",    "Pesagens"),
    ("anotacoes",   "Anotações"),
]


# ─── AUTENTICAÇÃO ─────────────────────────────────────────────────────────────

# Endpoints acessíveis sem login
ENDPOINTS_PUBLICOS = {"login", "static"}


@app.before_request
def exigir_login():
    if request.endpoint in ENDPOINTS_PUBLICOS:
        return
    if not session.get("usuario"):
        return redirect(url_for("login", next=request.path))


def login_required(f):
    # Mantido por compatibilidade; a proteção real é o before_request acima
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("usuario"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    db.garantir_usuario_padrao()  # cria a Luana na primeira vez

    if request.method == "POST":
        username = request.form.get("username", "")
        senha    = request.form.get("senha", "")
        user = db.verificar_login(username, senha)
        if user:
            session["usuario"] = user
            flash(f"Bem-vinda, {user['nome'] or user['username']}!", "success")
            destino = request.args.get("next") or url_for("dashboard")
            return redirect(destino)
        flash("Usuário ou senha incorretos.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Sessão encerrada.", "info")
    return redirect(url_for("login"))


@app.route("/conta", methods=["GET", "POST"])
@login_required
def conta():
    if request.method == "POST":
        atual = request.form.get("senha_atual", "")
        nova  = request.form.get("senha_nova", "")
        conf  = request.form.get("senha_conf", "")
        user  = db.verificar_login(session["usuario"]["username"], atual)
        if not user:
            flash("Senha atual incorreta.", "danger")
        elif nova != conf:
            flash("A confirmação não confere.", "danger")
        elif len(nova) < 4:
            flash("A nova senha deve ter ao menos 4 caracteres.", "danger")
        else:
            db.trocar_senha(session["usuario"]["id"], nova)
            flash("Senha alterada com sucesso!", "success")
        return redirect(url_for("conta"))
    return render_template("conta.html")


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
    fin = db.resumo_financeiro()
    return render_template("dashboard.html", stats=stats, fin=fin,
                           ultimos=db.ultimos_tickets(8))


# ─── FINANCEIRO ───────────────────────────────────────────────────────────────

@app.route("/financeiro")
def financeiro():
    fin     = db.resumo_financeiro()
    tickets = db.ultimos_tickets(30)
    return render_template("financeiro.html", fin=fin, tickets=tickets)


# ─── ATENDIMENTO RÁPIDO ───────────────────────────────────────────────────────

@app.route("/atendimento")
def atendimento():
    """Busca rápida de cliente para emitir ticket ou receita."""
    q      = request.args.get("q", "").strip()
    acao   = request.args.get("acao", "ticket")  # 'ticket' | 'receita'
    achados = []
    if q:
        clientes = db.buscar_clientes(q=q, limite=20)
        for c in clientes:
            animais = db.get_animais_cliente(c["id_cliente"])
            achados.append({"cliente": c, "animais": animais})
    return render_template("atendimento.html", q=q, acao=acao, achados=achados)


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
        dados = {k: request.form.get(k, "").strip()
                 for k in ("nome","cpf","celular","telefone",
                           "email","endereco","cidade","nascimento","observacao")}
        if not dados["nome"]:
            flash("Nome é obrigatório.", "danger")
            return render_template("novo_cliente.html", form=dados)
        id_novo = db.inserir_cliente(dados)
        flash(f"Cliente '{dados['nome']}' cadastrado!", "success")
        return redirect(url_for("cliente", id_cliente=f"new_{id_novo}"))
    return render_template("novo_cliente.html", form={})


@app.route("/clientes/<id_cliente>")
def cliente(id_cliente):
    dados     = db.get_cliente(id_cliente)
    animais   = db.get_animais_cliente(id_cliente)
    secao     = request.args.get("secao", "")
    id_animal = request.args.get("animal", "")
    registros = []
    if secao and id_animal:
        registros = db.get_registros_animal(id_cliente, id_animal, secao)

    # Receitas criadas no offline (quando a seção for receituário)
    receitas_criadas = []
    if secao == "receituario" and id_animal:
        receitas_criadas = db.get_receitas_animal(id_cliente, id_animal)

    tickets_imp, tickets_novos = db.get_tickets_cliente(id_cliente)

    return render_template("cliente.html",
                           cliente=dados,
                           id_cliente=id_cliente,
                           animais=animais,
                           secoes=SECOES,
                           secao_ativa=secao,
                           id_animal_ativo=id_animal,
                           registros=registros,
                           receitas_criadas=receitas_criadas,
                           tickets_imp=tickets_imp,
                           tickets_novos=tickets_novos)


# ─── ANIMAIS ──────────────────────────────────────────────────────────────────

@app.route("/clientes/<id_cliente>/novo-animal", methods=["GET", "POST"])
def novo_animal(id_cliente):
    cliente_dados = db.get_cliente(id_cliente)
    if request.method == "POST":
        dados = {k: request.form.get(k, "").strip()
                 for k in ("nome","especie","raca","sexo",
                           "nascimento","pelagem","chip","observacao")}
        dados["id_cliente"] = id_cliente
        if not dados["nome"]:
            flash("Nome do animal é obrigatório.", "danger")
            return render_template("novo_animal.html",
                                   cliente=cliente_dados,
                                   id_cliente=id_cliente, form=dados)
        db.inserir_animal(dados)
        flash(f"Animal '{dados['nome']}' cadastrado!", "success")
        return redirect(url_for("cliente", id_cliente=id_cliente))
    return render_template("novo_animal.html",
                           cliente=cliente_dados,
                           id_cliente=id_cliente, form={})


# ─── REGISTROS MÉDICOS ────────────────────────────────────────────────────────

@app.route("/clientes/<id_cliente>/animais/<id_animal>/novo-registro",
           methods=["GET", "POST"])
def novo_registro(id_cliente, id_animal):
    cliente_dados = db.get_cliente(id_cliente)
    tipo = request.args.get("tipo", "consulta")

    if request.method == "POST":
        tipo  = request.form.get("tipo", tipo)
        dados = {k: request.form.get(k, "").strip()
                 for k in ("data","descricao","veterinario","observacao")}
        dados.update({"tipo": tipo, "id_cliente": id_cliente,
                      "id_animal": id_animal, "arquivo": ""})

        arquivo = request.files.get("arquivo")
        if arquivo and arquivo.filename:
            pasta  = os.path.join("dados_exportados", "exames_pdf")
            os.makedirs(pasta, exist_ok=True)
            nome_f = f"manual_{id_cliente}_{id_animal}_{arquivo.filename}"
            caminho = os.path.join(pasta, nome_f)
            arquivo.save(caminho)
            dados["arquivo"] = caminho

        db.inserir_registro(dados)
        flash("Registro adicionado!", "success")
        return redirect(url_for("cliente", id_cliente=id_cliente,
                                animal=id_animal, secao=tipo + "s"))

    return render_template("novo_registro.html",
                           cliente=cliente_dados,
                           id_cliente=id_cliente,
                           id_animal=id_animal,
                           tipo=tipo, tipos=SECOES)


# ─── TICKETS ─────────────────────────────────────────────────────────────────

CLINICA = {
    "nome":     "Luana Feitosa — Atendimento Domiciliar",
    "endereco": "",
    "cidade":   "",
    "cep":      "",
    "tel1":     "(83) 99603-12",
    "tel2":     "",
    "email":    "info.luanafeitosa@gmail.com",
    "cnpj":     "",
}


@app.route("/clientes/<id_cliente>/animais/<id_animal>/ticket", methods=["GET", "POST"])
def novo_ticket(id_cliente, id_animal):
    cliente_dados = db.get_cliente(id_cliente)
    animais = db.get_animais_cliente(id_cliente)
    animal  = next((a for a in animais
                    if str(a.get("id_animal") or a.get("id","")) == str(id_animal)), {})
    servicos = db.get_servicos()

    if request.method == "POST":
        from datetime import date
        itens = []
        descricoes = request.form.getlist("descricao[]")
        tipos_svc  = request.form.getlist("tipo_svc[]")
        qtds       = request.form.getlist("qtd[]")
        valores    = request.form.getlist("valor[]")
        descontos  = request.form.getlist("desconto[]")

        total_svc  = 0.0
        total_prod = 0.0
        total_desc = 0.0

        for desc, tp, qtd, val, desc_val in zip(descricoes, tipos_svc, qtds, valores, descontos):
            if not desc.strip():
                continue
            try:
                v = float(val.replace(",", ".") or 0)
                q = int(qtd or 1)
                d = float(desc_val.replace(",", ".") or 0)
                sub = (v * q) - d
                if tp == "produto":
                    total_prod += sub
                else:
                    total_svc += sub
                total_desc += d
                itens.append({"descricao": desc, "tipo": tp, "qtd": q,
                               "valor": f"{v:.2f}".replace(".", ","),
                               "desconto": f"{d:.2f}".replace(".", ","),
                               "subtotal": f"{sub:.2f}".replace(".", ",")})
            except Exception:
                continue

        bruto   = total_svc + total_prod
        liquido = bruto - total_desc

        ticket = {
            "id":            db.proximo_id_ticket(),
            "data":          request.form.get("data", str(date.today().strftime("%d/%m/%Y"))),
            "veterinario":   request.form.get("veterinario", ""),
            "id_cliente":    id_cliente,
            "id_animal":     id_animal,
            "nome_cliente":  cliente_dados.get("nome", "") if cliente_dados else "",
            "cpf":           cliente_dados.get("cpf", "") if cliente_dados else "",
            "celular":       cliente_dados.get("celular", "") if cliente_dados else "",
            "email":         cliente_dados.get("email", "") if cliente_dados else "",
            "endereco":      cliente_dados.get("endereco", "") if cliente_dados else "",
            "cidade":        cliente_dados.get("cidade", "") if cliente_dados else "",
            "nome_animal":   animal.get("nome_animal") or animal.get("nome", ""),
            "especie":       animal.get("especie", ""),
            "raca":          animal.get("raca", ""),
            "pelagem":       animal.get("pelagem", ""),
            "nascimento":    animal.get("nascimento", ""),
            "sexo":          animal.get("sexo", ""),
            "chip":          animal.get("chip", ""),
            "itens":         itens,
            "total_servicos": f"{total_svc:.2f}".replace(".", ","),
            "total_produtos": f"{total_prod:.2f}".replace(".", ","),
            "total_bruto":    f"{bruto:.2f}".replace(".", ","),
            "total_descontos":f"{total_desc:.2f}".replace(".", ","),
            "total_liquido":  f"{liquido:.2f}".replace(".", ","),
        }
        db.salvar_ticket(ticket)
        return render_template("ticket.html", ticket=ticket, clinica=CLINICA)

    return render_template("novo_ticket.html",
                           cliente=cliente_dados,
                           animal=animal,
                           id_cliente=id_cliente,
                           id_animal=id_animal,
                           servicos=servicos)


@app.route("/ticket/<int:ticket_id>")
def ver_ticket(ticket_id):
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        flash("Ticket não encontrado.", "warning")
        return redirect(url_for("dashboard"))
    return render_template("ticket.html", ticket=ticket, clinica=CLINICA)


# ─── RECEITAS ─────────────────────────────────────────────────────────────────

@app.route("/clientes/<id_cliente>/animais/<id_animal>/receita", methods=["GET", "POST"])
def nova_receita(id_cliente, id_animal):
    cliente_dados = db.get_cliente(id_cliente)
    animais = db.get_animais_cliente(id_cliente)
    animal  = next((a for a in animais
                    if str(a.get("id_animal") or a.get("id","")) == str(id_animal)), {})

    if request.method == "POST":
        from datetime import date
        dados = {
            "id_cliente":  id_cliente,
            "id_animal":   id_animal,
            "tipo":        request.form.get("tipo", "simples"),
            "data":        request.form.get("data", date.today().strftime("%d/%m/%Y")),
            "veterinario": request.form.get("veterinario", "").strip(),
            "crmv":        request.form.get("crmv", "").strip(),
            "uso_oral":    request.form.get("uso_oral", "").strip(),
            "uso_topico":  request.form.get("uso_topico", "").strip(),
            "observacao":  request.form.get("observacao", "").strip(),
        }
        rid = db.salvar_receita(dados)
        flash("Receita criada! Abrindo para impressão...", "success")
        return redirect(url_for("ver_receita", receita_id=rid))

    return render_template("nova_receita.html",
                           cliente=cliente_dados, animal=animal,
                           id_cliente=id_cliente, id_animal=id_animal)


@app.route("/receita/<int:receita_id>")
def ver_receita(receita_id):
    receita = db.get_receita(receita_id)
    if not receita:
        flash("Receita não encontrada.", "warning")
        return redirect(url_for("dashboard"))

    cliente = db.get_cliente(receita["id_cliente"])
    animais = db.get_animais_cliente(receita["id_cliente"])
    animal  = next((a for a in animais
                    if str(a.get("id_animal") or a.get("id","")) == str(receita["id_animal"])), {})

    # Separa medicamentos por linha
    receita["oral_itens"]   = [l.strip() for l in (receita.get("uso_oral") or "").splitlines() if l.strip()]
    receita["topico_itens"] = [l.strip() for l in (receita.get("uso_topico") or "").splitlines() if l.strip()]

    return render_template("receita_print.html",
                           receita=receita, cliente=cliente,
                           animal=animal, clinica=CLINICA)


# ─── PDF LOCAL ────────────────────────────────────────────────────────────────

@app.route("/pdf")
def ver_pdf():
    caminho = request.args.get("f", "")
    if caminho and os.path.exists(caminho):
        return send_file(os.path.abspath(caminho), mimetype="application/pdf")
    flash("PDF não encontrado localmente.", "warning")
    return redirect(request.referrer or url_for("dashboard"))


if __name__ == "__main__":
    print("=" * 50)
    print("  VetSistema — Modo Offline")
    print("  http://localhost:5001")
    print("  Dados: dados_exportados/ (sem internet)")
    print("=" * 50)
    app.run(debug=False, port=5001)
