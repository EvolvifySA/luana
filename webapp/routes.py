"""
webapp/routes.py — Todas as rotas do Evolvify.

Registradas via register_routes(app) pela factory em __init__.py.
"""

from flask import (render_template, request, redirect,
                   url_for, flash, send_file, session)
from datetime import date, datetime
import calendar
import os

_NOMES_MES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
              "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _periodo_request():
    """Lê os filtros 'mes' (AAAA-MM) e 'dia' (AAAA-MM-DD) da URL.

    Retorna (inicio_iso, fim_iso, filtro) — filtro tem mes/dia/label para o template.
    Padrão: mês atual.
    """
    hoje = date.today()
    dia = (request.args.get("dia") or "").strip()
    mes = (request.args.get("mes") or "").strip()

    if dia:
        try:
            d = datetime.strptime(dia, "%Y-%m-%d").date()
            return (d.isoformat(), d.isoformat(),
                    {"mes": d.strftime("%Y-%m"), "dia": dia, "label": d.strftime("%d/%m/%Y")})
        except ValueError:
            pass

    if mes:
        try:
            ano, m = (int(x) for x in mes.split("-")[:2])
        except (ValueError, IndexError):
            ano, m = hoje.year, hoje.month
    else:
        ano, m = hoje.year, hoje.month
    if not (1 <= m <= 12):
        ano, m = hoje.year, hoje.month

    ultimo = calendar.monthrange(ano, m)[1]
    inicio = date(ano, m, 1)
    fim = date(ano, m, ultimo)
    return (inicio.isoformat(), fim.isoformat(),
            {"mes": f"{ano:04d}-{m:02d}", "dia": "", "label": f"{_NOMES_MES[m]}/{ano}"})

import config
from . import db
from .pdf_utils import pdf_context, render_pdf_response

SECOES = [
    ("consultas",   "Consultas"),
    ("vacinas",     "Vacinas"),
    ("receituario", "Receituário"),
    ("exames",      "Exames"),
    ("cirurgias",   "Cirurgias"),
    ("pesagens",    "Pesagens"),
    ("anotacoes",   "Anotações"),
]

ENDPOINTS_PUBLICOS = {"login", "solicitar_redefinicao", "redefinir_senha", "static"}

CONSULTA_FIELDS = [
    "consultation_date",
    "is_return",
    "return_date",
    "chief_complaint",
    "anamnesis",
    "digestive_system",
    "cardiorespiratory_system",
    "genitourinary_system",
    "nervous_musculoskeletal_system",
    "central_temperature",
    "peripheral_temperature",
    "heart_rate",
    "respiratory_rate",
    "tpc",
    "lymph_nodes",
    "mucosa",
    "hydration",
    "ectoparasites",
    "abdominal_palpation",
    "cardiac_auscultation",
    "pulmonary_auscultation",
    "blood_pressure",
    "glycemia",
    "delta",
    "weight",
    "clinical_suspicion",
    "requested_exams",
    "diagnosis",
    "outpatient_treatment",
    "integumentary_system",
    "previous_diseases_treatments",
    "observations",
    "veterinarian",
    "crmv",
    "status",
]


def _brl(valor):
    """Formata float -> '1.234,56'."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _consulta_blank(cliente=None, animal=None):
    hoje = date.today().isoformat()
    return {
        "id": "",
        "id_cliente": cliente.get("id_cliente") if cliente else "",
        "id_animal": animal.get("id_animal") if animal else "",
        "nome_cliente": cliente.get("nome") if cliente else "",
        "cpf": cliente.get("cpf") if cliente else "",
        "celular": cliente.get("celular") if cliente else "",
        "endereco": cliente.get("endereco") if cliente else "",
        "bairro": cliente.get("bairro") if cliente else "",
        "cidade": cliente.get("cidade") if cliente else "",
        "estado": cliente.get("estado") if cliente else "",
        "cep": cliente.get("cep") if cliente else "",
        "nome_animal": animal.get("nome_animal") if animal else "",
        "especie": animal.get("especie") if animal else "",
        "raca": animal.get("raca") if animal else "",
        "sexo": animal.get("sexo") if animal else "",
        "pelagem": animal.get("pelagem") if animal else "",
        "nascimento": animal.get("nascimento") if animal else "",
        "castrado": animal.get("castrado") if animal else "",
        "castrado_label": animal.get("castrado_label") if animal else "",
        "data_da_consulta": hoje,
        "is_retorno": False,
        "data_retorno": "",
        "status": "draft",
        "veterinario": "Luana Maria Feitosa Barroso",
        "crmv": "CRMV-PB 02956",
    }


# Campos clínicos que valem a pena copiar de uma consulta anterior
# (não copiamos data, retorno nem status — esses começam "do zero").
_CONSULTA_PREFILL_FIELDS = [f for f in CONSULTA_FIELDS
                            if f not in ("consultation_date", "is_return",
                                         "return_date", "status")]

# Alguns campos do exame têm chave em PT no dicionário da consulta.
_CONSULTA_PREFILL_FALLBACK = {
    "heart_rate": "freq_cardiaca",
    "respiratory_rate": "freq_respiratoria",
    "lymph_nodes": "linfonodos",
    "hydration": "hidratacao",
    "ectoparasites": "ectoparasitas",
    "abdominal_palpation": "palpacao_abdominal",
    "cardiac_auscultation": "ausculta_cardiaca",
    "pulmonary_auscultation": "ausculta_pulmonar",
    "blood_pressure": "pressao_arterial",
    "glycemia": "glicemia",
    "weight": "peso",
}


def _consulta_prefill(full):
    """Monta {campo_do_form: valor} a partir de uma consulta completa, para reaproveitar."""
    valores = {}
    for field in _CONSULTA_PREFILL_FIELDS:
        valor = full.get(field)
        if not valor and field in _CONSULTA_PREFILL_FALLBACK:
            valor = full.get(_CONSULTA_PREFILL_FALLBACK[field])
        valores[field] = valor or ""
    return {
        "id":        full.get("id", ""),
        "data":      full.get("data_da_consulta", ""),
        "descricao": (full.get("queixa_principal") or full.get("diagnostico") or "Consulta"),
        "valores":   valores,
    }


def _consulta_form_data():
    dados = {}
    for field in CONSULTA_FIELDS:
        dados[field] = request.form.get(field, "").strip()
    dados["is_return"] = request.form.get("is_return", "0").strip() in {"1", "true", "True", "sim"}
    dados["id_cliente"] = request.form.get("id_cliente", "").strip()
    dados["id_animal"] = request.form.get("id_animal", "").strip()
    dados["acao"] = request.form.get("acao", "salvar").strip()
    dados["completed_by"] = session.get("usuario", {}).get("nome") or session.get("usuario", {}).get("username") or ""
    return dados


def _idade_texto(nascimento):
    if not nascimento:
        return ""
    if isinstance(nascimento, date):
        nasc = nascimento
    else:
        texto = str(nascimento).strip()
        if not texto:
            return ""
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                nasc = datetime.strptime(texto, fmt).date()
                break
            except ValueError:
                nasc = None
        if not nasc:
            return ""
    hoje = date.today()
    anos = hoje.year - nasc.year - ((hoje.month, hoje.day) < (nasc.month, nasc.day))
    meses = hoje.month - nasc.month
    if hoje.day < nasc.day:
        meses -= 1
    meses %= 12
    if anos < 0:
        anos = 0
    return f"{anos} anos {meses} meses"


def register_routes(app):

    # ─── Autenticação (proteção global) ───────────────────────────────────────
    @app.before_request
    def exigir_login():
        if request.endpoint in ENDPOINTS_PUBLICOS:
            return
        if not session.get("usuario"):
            return redirect(url_for("login", next=request.path))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        db.garantir_usuario_padrao()
        if request.method == "POST":
            user = db.verificar_login(request.form.get("username", ""),
                                      request.form.get("senha", ""))
            if user:
                session["usuario"] = user
                flash(f"Bem-vinda, {user['nome'] or user['username']}!", "success")
                return redirect(request.args.get("next") or url_for("dashboard"))
            flash("Usuário ou senha incorretos.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("Sessão encerrada.", "info")
        return redirect(url_for("login"))

    @app.route("/conta", methods=["GET", "POST"])
    def conta():
        if request.method == "POST":
            atual = request.form.get("senha_atual", "")
            nova  = request.form.get("senha_nova", "")
            conf  = request.form.get("senha_conf", "")
            verif = db.verificar_login(session["usuario"]["username"], atual)
            if not verif:
                flash("Senha atual incorreta.", "danger")
            elif nova != conf:
                flash("A confirmação não confere.", "danger")
            elif len(nova) < 4:
                flash("A nova senha deve ter ao menos 4 caracteres.", "danger")
            else:
                try:
                    db.trocar_senha(
                        session["usuario"]["id"],
                        nova,
                        access_token=session["usuario"].get("auth_access_token") or verif.get("auth_access_token"),
                    )
                    flash("Senha alterada com sucesso!", "success")
                except Exception as exc:
                    flash(f"Nao foi possivel alterar a senha: {exc}", "danger")
            return redirect(url_for("conta"))
        return render_template("conta.html")

    @app.route("/esqueci-senha", methods=["GET", "POST"])
    def solicitar_redefinicao():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            if not username:
                flash("Informe o nome de usuário.", "danger")
                return render_template("esqueci_senha.html")
            try:
                db.solicitar_reset_senha(username, url_for("redefinir_senha", _external=True))
                flash("Se o usuário estiver configurado com e-mail, o link de redefinição foi enviado.", "success")
                return redirect(url_for("login"))
            except Exception as exc:
                flash(str(exc), "danger")
        return render_template("esqueci_senha.html")

    @app.route("/redefinir-senha", methods=["GET", "POST"])
    def redefinir_senha():
        token_hash = (
            request.values.get("token_hash")
            or request.values.get("token")
            or request.args.get("token_hash")
            or request.args.get("token")
            or ""
        ).strip()
        tipo = (request.values.get("type") or request.args.get("type") or "recovery").strip()
        redirect_to = request.args.get("redirect_to") or request.form.get("redirect_to") or ""
        if request.method == "POST":
            senha = request.form.get("senha_nova", "")
            conf = request.form.get("senha_conf", "")
            if not token_hash:
                flash("Link de redefinição inválido ou incompleto.", "danger")
            elif senha != conf:
                flash("A confirmação não confere.", "danger")
            elif len(senha) < 4:
                flash("A nova senha deve ter ao menos 4 caracteres.", "danger")
            else:
                try:
                    db.confirmar_reset_senha(token_hash, senha, tipo=tipo)
                    flash("Senha redefinida com sucesso. Você já pode entrar no sistema.", "success")
                    return redirect(url_for("login"))
                except Exception as exc:
                    flash(str(exc), "danger")
        return render_template(
            "redefinir_senha.html",
            token_hash=token_hash,
            tipo=tipo,
            redirect_to=redirect_to,
        )

    # ─── Dashboard ────────────────────────────────────────────────────────────
    @app.route("/")
    def dashboard():
        inicio, fim, filtro = _periodo_request()
        dados = db.dashboard_overview(inicio, fim)
        return render_template(
            "dashboard.html",
            stats=dados["stats"],
            fin=dados["fin"],
            ultimos=dados["ultimos"],
            filtro=filtro,
        )

    @app.route("/financeiro")
    def financeiro():
        inicio, fim, filtro = _periodo_request()
        return render_template("financeiro.html",
                               fin=db.resumo_financeiro(inicio, fim),
                               tickets=db.ultimos_tickets(500, inicio, fim),
                               filtro=filtro)

    # ─── Atendimento rápido ───────────────────────────────────────────────────
    @app.route("/ticket/<ticket_id>/status", methods=["POST"])
    def ticket_status(ticket_id):
        novo_status = (request.form.get("status") or "").strip().lower()
        if novo_status not in {"paid", "pending", "cancelled", "draft"}:
            flash("Status inválido para o ticket.", "warning")
            return redirect(request.referrer or url_for("financeiro"))
        try:
            db.atualizar_status_ticket(ticket_id, novo_status)
            flash("Status do ticket atualizado.", "success")
        except Exception as exc:
            flash(f"Não foi possível atualizar o ticket: {exc}", "danger")
        return redirect(request.referrer or url_for("financeiro"))

    @app.route("/atendimento")
    def atendimento():
        q    = request.args.get("q", "").strip()
        acao = request.args.get("acao", "ticket")
        achados = []
        if q:
            achados = db.buscar_clientes_com_animais(q=q, limite=20)
        return render_template("atendimento.html", q=q, acao=acao, achados=achados)

    # ─── Clientes ─────────────────────────────────────────────────────────────
    @app.route("/clientes")
    def clientes():
        q       = request.args.get("q", "").strip()
        pagina  = int(request.args.get("p", 1))
        por_pag = 50
        offset  = (pagina - 1) * por_pag
        clientes, total = db.buscar_clientes_paginado(q=q, limite=por_pag, offset=offset)
        return render_template("clientes.html",
                               clientes=clientes,
                               q=q, pagina=pagina,
                               paginas=(total + por_pag - 1) // por_pag)

    @app.route("/clientes/novo", methods=["GET", "POST"])
    def novo_cliente():
        if request.method == "POST":
            dados = {k: request.form.get(k, "").strip()
                     for k in ("nome", "cpf", "celular", "telefone",
                               "email", "endereco", "bairro", "cidade", "estado", "cep", "nascimento", "observacao")}
            if not dados["nome"]:
                flash("Nome é obrigatório.", "danger")
                return render_template("novo_cliente.html", form=dados)
            id_novo = db.inserir_cliente(dados)
            flash(f"Cliente '{dados['nome']}' cadastrado!", "success")
            return redirect(url_for("cliente", id_cliente=f"new_{id_novo}"))
        return render_template("novo_cliente.html", form={})

    @app.route("/clientes/<id_cliente>/editar", methods=["GET", "POST"])
    def editar_cliente(id_cliente):
        if request.method == "POST":
            dados = {k: request.form.get(k, "").strip()
                     for k in ("nome", "cpf", "celular", "telefone",
                               "email", "endereco", "bairro", "cidade", "estado", "cep", "nascimento", "observacao")}
            if not dados["nome"]:
                flash("Nome é obrigatório.", "danger")
                return render_template("novo_cliente.html", form=dados,
                                       editando=True, id_cliente=id_cliente)
            try:
                db.atualizar_cliente(id_cliente, dados)
                flash("Cliente atualizado!", "success")
                return redirect(url_for("cliente", id_cliente=id_cliente))
            except Exception as exc:
                flash(str(exc), "danger")
                return render_template("novo_cliente.html", form=dados,
                                       editando=True, id_cliente=id_cliente)
        cliente_dados = db.get_cliente(id_cliente)
        if not cliente_dados:
            flash("Cliente não encontrado.", "warning")
            return redirect(url_for("clientes"))
        return render_template("novo_cliente.html", form=cliente_dados,
                               editando=True, id_cliente=id_cliente)

    @app.route("/clientes/<id_cliente>")
    def cliente(id_cliente):
        secao     = request.args.get("secao", "")
        id_animal = request.args.get("animal", "")
        registros = []
        if secao and id_animal:
            if secao == "consultas":
                registros = db.get_consultas_animal(id_cliente, id_animal)
            elif secao == "receituario":
                # O receituário é renderizado a partir de `receitas_criadas`;
                # `registros` não é usado, então evitamos uma query inútil.
                pass
            else:
                registros = db.get_registros_animal(id_cliente, id_animal, secao)
        receitas_criadas = []
        if secao == "receituario" and id_animal:
            receitas_criadas = db.get_receitas_animal(id_cliente, id_animal)
        tickets_imp, tickets_novos = db.get_tickets_cliente(id_cliente)
        return render_template("cliente.html",
                               cliente=db.get_cliente(id_cliente),
                               id_cliente=id_cliente,
                               animais=db.get_animais_cliente(id_cliente),
                               secoes=SECOES, secao_ativa=secao,
                               id_animal_ativo=id_animal, registros=registros,
                               receitas_criadas=receitas_criadas,
                               tickets_imp=tickets_imp, tickets_novos=tickets_novos)

    @app.route("/clientes/<id_cliente>/apagar", methods=["POST"])
    def apagar_cliente(id_cliente):
        try:
            nome = db.apagar_cliente(id_cliente)
            flash(f"Cliente '{nome}' apagado.", "success")
            return redirect(url_for("clientes"))
        except Exception as exc:
            flash(str(exc), "danger")
            return redirect(url_for("cliente", id_cliente=id_cliente))

    # ─── Animais ──────────────────────────────────────────────────────────────
    @app.route("/clientes/<id_cliente>/novo-animal", methods=["GET", "POST"])
    def novo_animal(id_cliente):
        cliente_dados = db.get_cliente(id_cliente)
        if request.method == "POST":
            dados = {k: request.form.get(k, "").strip()
                     for k in ("nome", "especie", "raca", "sexo",
                               "nascimento", "pelagem", "chip", "castrado", "observacao")}
            dados["id_cliente"] = id_cliente
            if not dados["nome"]:
                flash("Nome do animal é obrigatório.", "danger")
                return render_template("novo_animal.html", cliente=cliente_dados,
                                       id_cliente=id_cliente, form=dados)
            db.inserir_animal(dados)
            flash(f"Animal '{dados['nome']}' cadastrado!", "success")
            return redirect(url_for("cliente", id_cliente=id_cliente))
        return render_template("novo_animal.html", cliente=cliente_dados,
                               id_cliente=id_cliente, form={})

    # ─── Registros médicos ────────────────────────────────────────────────────
    def _render_consulta_form(consulta, cliente, animal, consultas_anteriores=None):
        return render_template(
            "nova_consulta.html",
            cliente=cliente,
            animal=animal,
            id_cliente=cliente.get("id_cliente") if cliente else "",
            id_animal=animal.get("id_animal") if animal else "",
            consulta=consulta,
            consultas_anteriores=consultas_anteriores or [],
        )

    @app.route("/clientes/<id_cliente>/animais/<id_animal>/consulta", methods=["GET", "POST"])
    def nova_consulta(id_cliente, id_animal):
        cliente = db.get_cliente(id_cliente)
        animais = db.get_animais_cliente(id_cliente)
        animal = next((a for a in animais if str(a.get("id_animal") or a.get("id", "")) == str(id_animal)), {})
        if request.method == "POST":
            dados = _consulta_form_data()
            dados["id_cliente"] = id_cliente
            dados["id_animal"] = id_animal
            consulta_id = db.salvar_consulta(dados)
            flash("Consulta salva com sucesso!", "success")
            if dados["acao"] == "finalizar":
                return redirect(url_for("ver_consulta", consulta_id=consulta_id))
            return redirect(url_for("editar_consulta", consulta_id=consulta_id))
        # Consultas anteriores deste animal (completas) para reaproveitar
        consultas_anteriores = []
        for c in db.get_consultas_animal(id_cliente, id_animal):
            full = db.get_consulta(c.get("id"))
            if full:
                consultas_anteriores.append(_consulta_prefill(full))
        return _render_consulta_form(_consulta_blank(cliente, animal), cliente, animal,
                                     consultas_anteriores)

    @app.route("/consultas/<consulta_id>", methods=["GET", "POST"])
    def editar_consulta(consulta_id):
        consulta = db.get_consulta(consulta_id)
        if not consulta:
            flash("Consulta não encontrada.", "warning")
            return redirect(url_for("dashboard"))
        cliente = consulta.get("cliente") or db.get_cliente(consulta.get("id_cliente"))
        animal = consulta.get("animal") or {}
        if request.method == "POST":
            dados = _consulta_form_data()
            dados["id"] = consulta_id
            dados["id_cliente"] = consulta.get("id_cliente")
            dados["id_animal"] = consulta.get("id_animal")
            consulta_id = db.salvar_consulta(dados)
            flash("Consulta atualizada!", "success")
            if dados["acao"] == "finalizar":
                return redirect(url_for("ver_consulta", consulta_id=consulta_id))
            if dados["acao"] == "cancelar":
                return redirect(url_for("cliente", id_cliente=dados["id_cliente"], animal=dados["id_animal"], secao="consultas"))
            return redirect(url_for("editar_consulta", consulta_id=consulta_id))
        return _render_consulta_form(consulta, cliente, animal)

    @app.route("/consultas/<consulta_id>/ver")
    def ver_consulta(consulta_id):
        consulta = db.get_consulta(consulta_id)
        if not consulta:
            flash("Consulta não encontrada.", "warning")
            return redirect(url_for("dashboard"))
        cliente = consulta.get("cliente") or db.get_cliente(consulta.get("id_cliente"))
        animal = consulta.get("animal") or {}
        return render_template(
            "consulta_print.html",
            **pdf_context(
                consulta=consulta,
                cliente=cliente,
                animal=animal,
                animal_idade=_idade_texto(animal.get("nascimento")),
                clinica=config.CLINICA,
            ),
        )

    @app.route("/consultas/<consulta_id>/pdf")
    def consulta_pdf(consulta_id):
        consulta = db.get_consulta(consulta_id)
        if not consulta:
            flash("Consulta não encontrada.", "warning")
            return redirect(url_for("dashboard"))
        cliente = consulta.get("cliente") or db.get_cliente(consulta.get("id_cliente"))
        animal = consulta.get("animal") or {}
        return render_pdf_response(
            "consulta_print.html",
            f"consulta-{consulta_id}.pdf",
            **pdf_context(
                consulta=consulta,
                cliente=cliente,
                animal=animal,
                animal_idade=_idade_texto(animal.get("nascimento")),
                clinica=config.CLINICA,
            ),
        )

    @app.route("/clientes/<id_cliente>/animais/<id_animal>/novo-registro",
               methods=["GET", "POST"])
    def novo_registro(id_cliente, id_animal):
        cliente_dados = db.get_cliente(id_cliente)
        tipo = request.args.get("tipo", "consulta")
        if request.method == "GET" and tipo == "consulta":
            return redirect(url_for("nova_consulta", id_cliente=id_cliente, id_animal=id_animal))
        if request.method == "POST":
            tipo  = request.form.get("tipo", tipo)
            dados = {k: request.form.get(k, "").strip()
                     for k in ("data", "descricao", "veterinario", "observacao")}
            dados.update({"tipo": tipo, "id_cliente": id_cliente,
                          "id_animal": id_animal, "arquivo": ""})
            arquivo = request.files.get("arquivo")
            if arquivo and arquivo.filename:
                pasta = os.path.join(config.OUTPUT_DIR, "exames_pdf")
                os.makedirs(pasta, exist_ok=True)
                caminho = os.path.join(pasta, f"manual_{id_cliente}_{id_animal}_{arquivo.filename}")
                arquivo.save(caminho)
                dados["arquivo"] = caminho
            db.inserir_registro(dados)
            flash("Registro adicionado!", "success")
            return redirect(url_for("cliente", id_cliente=id_cliente,
                                    animal=id_animal, secao=tipo + "s"))
        return render_template("novo_registro.html", cliente=cliente_dados,
                               id_cliente=id_cliente, id_animal=id_animal,
                               tipo=tipo, tipos=SECOES)

    # ─── Tickets ──────────────────────────────────────────────────────────────
    @app.route("/clientes/<id_cliente>/animais/<id_animal>/ticket",
               methods=["GET", "POST"])
    def novo_ticket(id_cliente, id_animal):
        cliente_dados = db.get_cliente(id_cliente)
        animais = db.get_animais_cliente(id_cliente)
        animal  = next((a for a in animais
                        if str(a.get("id_animal") or a.get("id", "")) == str(id_animal)), {})

        if request.method == "POST":
            itens, total_svc, total_prod, total_desc = [], 0.0, 0.0, 0.0
            campos = zip(request.form.getlist("descricao[]"),
                         request.form.getlist("tipo_svc[]"),
                         request.form.getlist("qtd[]"),
                         request.form.getlist("valor[]"),
                         request.form.getlist("desconto[]"))
            for desc, tp, qtd, val, desc_val in campos:
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
                except (ValueError, TypeError):
                    continue

            bruto   = total_svc + total_prod
            liquido = bruto - total_desc
            c = cliente_dados or {}
            ticket = {
                "id":            db.proximo_id_ticket(),
                "data":          request.form.get("data", date.today().strftime("%d/%m/%Y")),
                "veterinario":   request.form.get("veterinario", ""),
                "id_cliente":    id_cliente, "id_animal": id_animal,
                "nome_cliente":  c.get("nome", ""), "cpf": c.get("cpf", ""),
                "celular":       c.get("celular", ""), "email": c.get("email", ""),
                "endereco":      c.get("endereco", ""), "cidade": c.get("cidade", ""),
                "nome_animal":   animal.get("nome_animal") or animal.get("nome", ""),
                "especie":       animal.get("especie", ""), "raca": animal.get("raca", ""),
                "pelagem":       animal.get("pelagem", ""), "nascimento": animal.get("nascimento", ""),
                "sexo":          animal.get("sexo", ""), "chip": animal.get("chip", ""),
                "itens":         itens,
                "total_servicos": f"{total_svc:.2f}".replace(".", ","),
                "total_produtos": f"{total_prod:.2f}".replace(".", ","),
                "total_bruto":    f"{bruto:.2f}".replace(".", ","),
                "total_descontos": f"{total_desc:.2f}".replace(".", ","),
                "total_liquido":  f"{liquido:.2f}".replace(".", ","),
            }
            saved_ticket_id = db.salvar_ticket(ticket)
            ticket["id"] = saved_ticket_id or ticket["id"]
            return render_template("ticket.html", **pdf_context(ticket=ticket, clinica=config.CLINICA))

        # Tickets anteriores deste animal (com itens) para reaproveitar
        _, tickets_cli = db.get_tickets_cliente(id_cliente)
        tickets_anteriores = []
        for t in tickets_cli:
            full = db.get_ticket(t.get("id"))
            if full and str(full.get("id_animal")) == str(id_animal) and full.get("itens"):
                tickets_anteriores.append({
                    "id":    full.get("id"),
                    "data":  full.get("data", ""),
                    "total": full.get("total_liquido", ""),
                    "itens": full.get("itens", []),
                })
        return render_template("novo_ticket.html", cliente=cliente_dados, animal=animal,
                               id_cliente=id_cliente, id_animal=id_animal,
                               servicos=db.get_servicos(),
                               tickets_anteriores=tickets_anteriores)

    @app.route("/ticket/<ticket_id>")
    def ver_ticket(ticket_id):
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            flash("Ticket não encontrado.", "warning")
            return redirect(url_for("dashboard"))
        return render_template("ticket.html", **pdf_context(ticket=ticket, clinica=config.CLINICA))

    @app.route("/ticket/<ticket_id>/pdf")
    def ticket_pdf(ticket_id):
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            flash("Ticket não encontrado.", "warning")
            return redirect(url_for("dashboard"))
        return render_pdf_response(
            "ticket.html",
            f"ticket-{ticket_id}.pdf",
            **pdf_context(ticket=ticket, clinica=config.CLINICA),
        )

    # ─── Receitas ─────────────────────────────────────────────────────────────
    @app.route("/clientes/<id_cliente>/animais/<id_animal>/receita",
               methods=["GET", "POST"])
    def nova_receita(id_cliente, id_animal):
        cliente_dados = db.get_cliente(id_cliente)
        animais = db.get_animais_cliente(id_cliente)
        animal  = next((a for a in animais
                        if str(a.get("id_animal") or a.get("id", "")) == str(id_animal)), {})
        if request.method == "POST":
            dados = {
                "id_cliente": id_cliente, "id_animal": id_animal,
                "tipo":        request.form.get("tipo", "simples"),
                "data":        request.form.get("data", date.today().strftime("%d/%m/%Y")),
                "veterinario": request.form.get("veterinario", "").strip(),
                "crmv":        request.form.get("crmv", "").strip(),
                "uso_oral":    request.form.get("uso_oral", "").strip(),
                "uso_topico":  request.form.get("uso_topico", "").strip(),
                "observacao":  request.form.get("observacao", "").strip(),
            }
            rid = db.salvar_receita(dados)
            dados["id"] = rid
            # Salvar como receita personalizada (modelo reutilizável)?
            if request.form.get("salvar_template"):
                nome_tpl = request.form.get("template_nome", "").strip()
                try:
                    db.salvar_receita_template(nome_tpl, dados)
                    flash(f"Receita personalizada '{nome_tpl}' salva!", "success")
                except Exception as exc:
                    flash(f"Receita criada, mas não consegui salvar o modelo: {exc}", "warning")
            flash("Receita criada! Abrindo para impressão...", "success")
            return redirect(url_for("ver_receita", receita_id=rid))
        receitas_anteriores = db.get_receitas_animal(id_cliente, id_animal)
        receitas_personalizadas = db.get_receita_templates()
        return render_template("nova_receita.html", cliente=cliente_dados,
                               animal=animal, id_cliente=id_cliente, id_animal=id_animal,
                               receitas_anteriores=receitas_anteriores,
                               receitas_personalizadas=receitas_personalizadas)

    @app.route("/receitas-personalizadas")
    def receitas_personalizadas():
        return render_template("receitas_personalizadas.html",
                               templates=db.get_receita_templates())

    def _receita_template_form_data():
        return {k: request.form.get(k, "").strip()
                for k in ("nome", "tipo", "veterinario", "crmv",
                          "uso_oral", "uso_topico", "observacao")}

    @app.route("/receitas-personalizadas/nova", methods=["GET", "POST"])
    def nova_receita_personalizada():
        if request.method == "POST":
            dados = _receita_template_form_data()
            try:
                db.salvar_receita_template(dados.get("nome"), dados)
                flash("Receita personalizada criada!", "success")
                return redirect(url_for("receitas_personalizadas"))
            except Exception as exc:
                flash(str(exc), "danger")
                return render_template("receita_personalizada_form.html",
                                       form=dados, editando=False)
        return render_template("receita_personalizada_form.html",
                               form={"veterinario": "Luana Maria Feitosa Barroso",
                                     "crmv": "CRMV-PB 02956", "tipo": "simples"},
                               editando=False)

    @app.route("/receitas-personalizadas/<template_id>/editar", methods=["GET", "POST"])
    def editar_receita_personalizada(template_id):
        if request.method == "POST":
            dados = _receita_template_form_data()
            try:
                db.atualizar_receita_template(template_id, dados)
                flash("Receita personalizada atualizada!", "success")
                return redirect(url_for("receitas_personalizadas"))
            except Exception as exc:
                flash(str(exc), "danger")
                return render_template("receita_personalizada_form.html",
                                       form=dados, editando=True, template_id=template_id)
        tpl = db.get_receita_template(template_id)
        if not tpl:
            flash("Receita personalizada não encontrada.", "warning")
            return redirect(url_for("receitas_personalizadas"))
        return render_template("receita_personalizada_form.html",
                               form=tpl, editando=True, template_id=template_id)

    @app.route("/receitas-personalizadas/<template_id>/apagar", methods=["POST"])
    def apagar_receita_personalizada(template_id):
        try:
            db.apagar_receita_template(template_id)
            flash("Receita personalizada apagada.", "success")
        except Exception as exc:
            flash(f"Não foi possível apagar: {exc}", "danger")
        return redirect(url_for("receitas_personalizadas"))

    @app.route("/receita/<receita_id>")
    def ver_receita(receita_id):
        receita = db.get_receita(receita_id)
        if not receita:
            flash("Receita não encontrada.", "warning")
            return redirect(url_for("dashboard"))
        animais = db.get_animais_cliente(receita["id_cliente"])
        animal  = next((a for a in animais
                        if str(a.get("id_animal") or a.get("id", "")) == str(receita["id_animal"])), {})
        receita["oral_itens"]   = [l.strip() for l in (receita.get("uso_oral") or "").splitlines() if l.strip()]
        receita["topico_itens"] = [l.strip() for l in (receita.get("uso_topico") or "").splitlines() if l.strip()]
        return render_template(
            "receita_print.html",
            **pdf_context(
                receita=receita,
                cliente=db.get_cliente(receita["id_cliente"]),
                animal=animal,
                clinica=config.CLINICA,
            ),
        )

    @app.route("/receita/<receita_id>/pdf")
    def receita_pdf(receita_id):
        receita = db.get_receita(receita_id)
        if not receita:
            flash("Receita não encontrada.", "warning")
            return redirect(url_for("dashboard"))
        animais = db.get_animais_cliente(receita["id_cliente"])
        animal  = next((a for a in animais
                        if str(a.get("id_animal") or a.get("id", "")) == str(receita["id_animal"])), {})
        receita["oral_itens"]   = [l.strip() for l in (receita.get("uso_oral") or "").splitlines() if l.strip()]
        receita["topico_itens"] = [l.strip() for l in (receita.get("uso_topico") or "").splitlines() if l.strip()]
        return render_pdf_response(
            "receita_print.html",
            f"receita-{receita_id}.pdf",
            **pdf_context(
                receita=receita,
                cliente=db.get_cliente(receita["id_cliente"]),
                animal=animal,
                clinica=config.CLINICA,
            ),
        )

    # ─── PDF local ────────────────────────────────────────────────────────────
    @app.route("/pdf")
    def ver_pdf():
        caminho = request.args.get("f", "")
        if caminho and os.path.exists(caminho):
            return send_file(os.path.abspath(caminho), mimetype="application/pdf")
        flash("PDF não encontrado localmente.", "warning")
        return redirect(request.referrer or url_for("dashboard"))
