"""
webapp/routes.py — Todas as rotas do Evolvify.

Registradas via register_routes(app) pela factory em __init__.py.
"""

from flask import (render_template, request, redirect,
                   url_for, flash, send_file, session)
from datetime import date
import os

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

ENDPOINTS_PUBLICOS = {"login", "static"}


def _brl(valor):
    """Formata float -> '1.234,56'."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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
            if not db.verificar_login(session["usuario"]["username"], atual):
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

    # ─── Dashboard ────────────────────────────────────────────────────────────
    @app.route("/")
    def dashboard():
        stats = {
            "clientes":  db.total_clientes(),
            "animais":   db.total_animais(),
            "consultas": db.total_registros("consultas"),
            "vacinas":   db.total_registros("vacinas"),
            "exames":    db.total_registros("exames"),
        }
        return render_template("dashboard.html", stats=stats,
                               fin=db.resumo_financeiro(),
                               ultimos=db.ultimos_tickets(8))

    @app.route("/financeiro")
    def financeiro():
        return render_template("financeiro.html",
                               fin=db.resumo_financeiro(),
                               tickets=db.ultimos_tickets(30))

    # ─── Atendimento rápido ───────────────────────────────────────────────────
    @app.route("/atendimento")
    def atendimento():
        q    = request.args.get("q", "").strip()
        acao = request.args.get("acao", "ticket")
        achados = []
        if q:
            for c in db.buscar_clientes(q=q, limite=20):
                achados.append({"cliente": c,
                                "animais": db.get_animais_cliente(c["id_cliente"])})
        return render_template("atendimento.html", q=q, acao=acao, achados=achados)

    # ─── Clientes ─────────────────────────────────────────────────────────────
    @app.route("/clientes")
    def clientes():
        q       = request.args.get("q", "").strip()
        pagina  = int(request.args.get("p", 1))
        por_pag = 50
        offset  = (pagina - 1) * por_pag
        total   = db.total_clientes()
        return render_template("clientes.html",
                               clientes=db.buscar_clientes(q=q, limite=por_pag, offset=offset),
                               q=q, pagina=pagina,
                               paginas=(total + por_pag - 1) // por_pag)

    @app.route("/clientes/novo", methods=["GET", "POST"])
    def novo_cliente():
        if request.method == "POST":
            dados = {k: request.form.get(k, "").strip()
                     for k in ("nome", "cpf", "celular", "telefone",
                               "email", "endereco", "cidade", "nascimento", "observacao")}
            if not dados["nome"]:
                flash("Nome é obrigatório.", "danger")
                return render_template("novo_cliente.html", form=dados)
            id_novo = db.inserir_cliente(dados)
            flash(f"Cliente '{dados['nome']}' cadastrado!", "success")
            return redirect(url_for("cliente", id_cliente=f"new_{id_novo}"))
        return render_template("novo_cliente.html", form={})

    @app.route("/clientes/<id_cliente>")
    def cliente(id_cliente):
        secao     = request.args.get("secao", "")
        id_animal = request.args.get("animal", "")
        registros = []
        if secao and id_animal:
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

    # ─── Animais ──────────────────────────────────────────────────────────────
    @app.route("/clientes/<id_cliente>/novo-animal", methods=["GET", "POST"])
    def novo_animal(id_cliente):
        cliente_dados = db.get_cliente(id_cliente)
        if request.method == "POST":
            dados = {k: request.form.get(k, "").strip()
                     for k in ("nome", "especie", "raca", "sexo",
                               "nascimento", "pelagem", "chip", "observacao")}
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
    @app.route("/clientes/<id_cliente>/animais/<id_animal>/novo-registro",
               methods=["GET", "POST"])
    def novo_registro(id_cliente, id_animal):
        cliente_dados = db.get_cliente(id_cliente)
        tipo = request.args.get("tipo", "consulta")
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
            db.salvar_ticket(ticket)
            return render_template("ticket.html", **pdf_context(ticket=ticket, clinica=config.CLINICA))

        return render_template("novo_ticket.html", cliente=cliente_dados, animal=animal,
                               id_cliente=id_cliente, id_animal=id_animal,
                               servicos=db.get_servicos())

    @app.route("/ticket/<int:ticket_id>")
    def ver_ticket(ticket_id):
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            flash("Ticket não encontrado.", "warning")
            return redirect(url_for("dashboard"))
        return render_template("ticket.html", **pdf_context(ticket=ticket, clinica=config.CLINICA))

    @app.route("/ticket/<int:ticket_id>/pdf")
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
            flash("Receita criada! Abrindo para impressão...", "success")
            return redirect(url_for("ver_receita", receita_id=rid))
        return render_template("nova_receita.html", cliente=cliente_dados,
                               animal=animal, id_cliente=id_cliente, id_animal=id_animal)

    @app.route("/receita/<int:receita_id>")
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

    @app.route("/receita/<int:receita_id>/pdf")
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
