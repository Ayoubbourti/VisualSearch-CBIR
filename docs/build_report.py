"""
Génère le rapport du projet (Word .docx, puis PDF si LibreOffice est installé).

    python docs/build_report.py --authors "Nom1, Nom2, Nom3" --group G6 \
        --results results/eval_classic_summary.csv --strict results/eval_strict_summary.csv \
        [--screens docs/screens]

* Les chiffres d'évaluation sont LUS dans les CSV produits par scripts/evaluate.py : rien n'est écrit « à la main ».
  Sans CSV, la section « Résultats » affiche un encadré indiquant la commande à exécuter.
* --screens : dossier de captures d'écran (dashboard.png, gallery.png, detail.png, search.png, feedback.png)
  insérées en annexe si elles existent.
* La table des matières est paginée en deux passes (génération -> PDF -> lecture des pages -> régénération).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))
import diagrams                              # noqa: E402
from make_figures import plot_summary, read_summary   # noqa: E402

# Valeurs mesurées sur ce dépôt (pytest --cov) ; à mettre à jour si le code évolue.
N_TESTS, COVERAGE = 144, 94
FONT, MONO = "Arial", "Courier New"
ACCENT = RGBColor(0x1E, 0x3A, 0x5F)

# Indices de la prose (les équations LaTeX gardent leur notation d'origine)
SUBSCRIPTS = [("σ_rel,i", "σrel,i"), ("σ_Nr,i", "σNr,i"), ("σ_rel", "σrel"), ("σ_Nr", "σNr"), ("w_i", "wᵢ"),
              ("b_i", "bᵢ"), ("n_g", "nɡ"), ("N_r", "Nᵣ")]

EQ = {
    "hist": r"N_{bins}=N_H\times N_S\times N_V=8\times3\times3=72",
    "mean": r"\mu_c=\frac{1}{N}\sum_{j=1}^{N}x_{j}\qquad \sigma_c=\sqrt{\frac{1}{N}\sum_{j=1}^{N}(x_j-\mu_c)^2}\qquad s_c=\frac{1}{N}\sum_{j=1}^{N}\left(\frac{x_j-\mu_c}{\sigma_c}\right)^3",
    "glcm": r"\mathrm{Contraste}=\sum_{i,j}(i-j)^2\,p_{ij}\qquad \mathrm{Homog\acute{e}n\acute{e}it\acute{e}}=\sum_{i,j}\frac{p_{ij}}{1+|i-j|}\qquad \mathrm{\acute{E}nergie}=\sum_{i,j}p_{ij}^2",
    "glcm2": r"\mathrm{Dissimilarit\acute{e}}=\sum_{i,j}|i-j|\,p_{ij}\qquad \mathrm{Corr\acute{e}lation}=\sum_{i,j}\frac{(i-\mu_i)(j-\mu_j)\,p_{ij}}{\sigma_i\sigma_j}\qquad \mathrm{Entropie}=-\sum_{i,j}p_{ij}\log_2 p_{ij}",
    "lbp": r"LBP_{P,R}=\sum_{p=0}^{P-1}s(g_p-g_c)\,2^{p},\qquad \;s(x)=1\ \mathrm{si}\ x\geq 0,\ 0\ \mathrm{sinon}",
    "zscore": r"Z_{ij}=\frac{X_{ij}-\mu_j}{\sigma_j}",
    "dist": r"D(Z_x,Z_y)=\sqrt{\frac{\sum_{i=1}^{97}w_i\,b_i\,(Z_{x,i}-Z_{y,i})^2}{\sum_{i=1}^{97}w_i\,b_i}}\qquad b_i=\frac{1}{n_g}",
    "type1": r"w_i^{(k+1)}=\frac{\varepsilon+\sigma_{N_r,i}^{(k)}}{\varepsilon+\sigma_{rel,i}^{(k)}},\qquad \varepsilon=10^{-4}",
    "query": r"Q^{(k+1)}=\frac{1}{|R|}\sum_{x\in R}Z_x",
    "clip": r"w_i\leftarrow\min\!\left(\max\!\left(w_i,\frac{\tilde{w}}{\rho}\right),\tilde{w}\,\rho\right),\qquad w\leftarrow w\cdot\frac{97}{\sum_i w_i}\qquad(\rho=20)",
    "prec": r"P@K=\frac{|\{\mathrm{pertinents}\}\cap Top_K|}{K}\qquad R@K=\frac{|\{\mathrm{pertinents}\}\cap Top_K|}{|\{\mathrm{pertinents}\}|}",
    "ap": r"AP@K=\frac{1}{\min(K,|Rel|)}\sum_{k=1}^{K}P@k\cdot rel_k\qquad nDCG@K=\frac{\sum_{k=1}^{K}rel_k/\log_2(k+1)}{\sum_{k=1}^{\min(K,|Rel|)}1/\log_2(k+1)}",
}


# =========================================================================== #
# Utilitaires python-docx
# =========================================================================== #
class Report:
    def __init__(self, tmp: Path, toc_pages: dict[str, int] | None = None):
        self.doc = Document()
        self.tmp, self.toc_pages = tmp, toc_pages or {}
        self.headings: list[tuple[int, str]] = []
        self.fig_n = self.tab_n = self.eq_n = 0
        self._setup()

    # ---- mise en page
    def _setup(self):
        d = self.doc
        s = d.sections[0]
        s.page_width, s.page_height = Cm(21), Cm(29.7)
        s.left_margin = s.right_margin = Cm(2.3)
        s.top_margin, s.bottom_margin = Cm(2.2), Cm(2.2)
        st = d.styles["Normal"]
        st.font.name, st.font.size = FONT, Pt(10.5)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        st.paragraph_format.space_after, st.paragraph_format.line_spacing = Pt(6), 1.25
        for lvl, size, before in ((1, 17, 18), (2, 13, 14), (3, 11, 10)):
            h = d.styles[f"Heading {lvl}"]
            h.font.name, h.font.size, h.font.bold, h.font.color.rgb = FONT, Pt(size), True, ACCENT
            h.element.rPr.rFonts.set(qn("w:ascii"), FONT)
            h.element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
            h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(before), Pt(6)
            h.paragraph_format.keep_with_next = True

    def footer(self):
        sec = self.doc.sections[-1]
        sec.different_first_page_header_footer = True
        p = sec.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("VisualSearch — Rapport de projet   |   Page ")
        r.font.size = Pt(8.5); r.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        run = p.add_run()
        run.font.size = Pt(8.5)
        for t, txt in (("begin", None), (None, "PAGE"), ("end", None)):
            if t:
                el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), t)
            else:
                el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = txt
            run._r.append(el)

    # ---- texte
    def runs(self, p, text, size=None, color=None):
        """Mini-balisage : **gras**, *italique*, `code`."""
        for part in re.split(r"(\*\*.+?\*\*|\*.+?\*|`.+?`)", text):
            if not part:
                continue
            if not part.startswith("`"):
                for a_, b_ in SUBSCRIPTS:
                    part = part.replace(a_, b_)
            if part.startswith("**"):
                r = p.add_run(part[2:-2]); r.bold = True
            elif part.startswith("`"):
                r = p.add_run(part[1:-1]); r.font.name = MONO; r.font.size = Pt(9.2)
                r._r.rPr.rFonts.set(qn("w:eastAsia"), MONO)
            elif part.startswith("*"):
                r = p.add_run(part[1:-1]); r.italic = True
            else:
                r = p.add_run(part)
            if size and not part.startswith("`"):
                r.font.size = Pt(size)
            if color:
                r.font.color.rgb = color
        return p

    def h(self, level, text):
        self.headings.append((level, text))
        return self.doc.add_heading(text, level)

    def p(self, text, align=None, **kw):
        para = self.doc.add_paragraph()
        para.alignment = align if align is not None else WD_ALIGN_PARAGRAPH.JUSTIFY
        return self.runs(para, text, **kw)

    def bullets(self, items, style="List Bullet"):
        for it in items:
            para = self.doc.add_paragraph(style=style)
            para.paragraph_format.space_after = Pt(2)
            self.runs(para, it)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def numbered(self, items):
        self.bullets(items, "List Number")

    def shade(self, cell_or_par, hex_fill):
        el = cell_or_par._tc if hasattr(cell_or_par, "_tc") else cell_or_par._p
        pr = el.get_or_add_tcPr() if hasattr(cell_or_par, "_tc") else el.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
        pr.append(shd)

    def code(self, text):
        for line in text.strip("\n").split("\n"):
            para = self.doc.add_paragraph()
            para.paragraph_format.space_after = Pt(0); para.paragraph_format.line_spacing = 1.0
            para.paragraph_format.left_indent = Cm(0.3)
            r = para.add_run(line or " "); r.font.name = MONO; r.font.size = Pt(8.6)
            r._r.rPr.rFonts.set(qn("w:eastAsia"), MONO)
            self.shade(para, "F1F5F9")
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def note(self, title, text, fill="FEF3C7"):
        t = self.doc.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        c = t.rows[0].cells[0]
        self.shade(c, fill)
        c.paragraphs[0].paragraph_format.space_after = Pt(2)
        self.runs(c.paragraphs[0], f"**{title}**")
        for line in text.split("\n"):
            para = c.add_paragraph(); para.paragraph_format.space_after = Pt(2)
            self.runs(para, line, size=9.5)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # ---- tableaux / figures / équations
    def table(self, header, rows, widths=None, caption=None, font=9, align_right_from=None):
        if caption:
            self.tab_n += 1
            cp = self.doc.add_paragraph()
            cp.paragraph_format.keep_with_next = True
            self.runs(cp, f"**Tableau {self.tab_n}** — {caption}", size=9.5)
        t = self.doc.add_table(rows=1, cols=len(header))
        t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, txt in enumerate(header):
            c = t.rows[0].cells[i]; self.shade(c, "1E3A5F")
            c.paragraphs[0].paragraph_format.space_after = Pt(1)
            r = c.paragraphs[0].add_run(txt); r.bold = True; r.font.size = Pt(font); r.font.color.rgb = RGBColor(255, 255, 255)
        for ri, row in enumerate(rows):
            cells = t.add_row().cells
            for i, txt in enumerate(row):
                para = cells[i].paragraphs[0]
                para.paragraph_format.space_after = Pt(1); para.paragraph_format.line_spacing = 1.1
                if align_right_from is not None and i >= align_right_from:
                    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                self.runs(para, str(txt), size=font)
                if ri % 2:
                    self.shade(cells[i], "F1F5F9")
        if widths:
            t.autofit = False
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(4)

    def figure(self, path: Path, caption: str, width_cm=15.5):
        self.fig_n += 1
        para = self.doc.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.keep_with_next = True
        para.add_run().add_picture(str(path), width=Cm(width_cm))
        cp = self.doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.runs(cp, f"**Figure {self.fig_n}** — {caption}", size=9)

    def eq(self, key, number=True, width_cm=None):
        path = self.tmp / f"eq_{key}.png"
        diagrams.equation(EQ[key], path)
        from PIL import Image
        w_px, _ = Image.open(path).size
        width = width_cm or min(15.5, w_px / 220 * 2.54)         # 220 dpi
        para = self.doc.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_before = para.paragraph_format.space_after = Pt(4)
        para.add_run().add_picture(str(path), width=Cm(width))
        if number:
            self.eq_n += 1
            self.runs(para, f"   ({self.eq_n})", size=9.5)

    def page_break(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def toc(self):
        self.h_plain("Table des matières")
        entries = [(lvl, t) for lvl, t in self.TOC_ENTRIES if lvl <= 2]
        for lvl, title in entries:
            para = self.doc.add_paragraph()
            para.paragraph_format.space_after = Pt(1 if lvl == 2 else 3)
            para.paragraph_format.left_indent = Cm(0.7 * (lvl - 1))
            para.paragraph_format.tab_stops.add_tab_stop(Cm(16.4), alignment=2, leader=1)   # RIGHT + points
            page = self.toc_pages.get(title, "")
            r = para.add_run(f"{title}\t{page}"); r.font.size = Pt(10 if lvl == 1 else 9.5); r.bold = lvl == 1

    def h_plain(self, text):
        para = self.doc.add_paragraph()
        r = para.add_run(text); r.bold = True; r.font.size = Pt(17); r.font.color.rgb = ACCENT
        para.paragraph_format.space_after = Pt(10)


# =========================================================================== #
# Contenu
# =========================================================================== #
def fmt_pct(x):
    return f"{x * 100:.2f} %"


def results_section(R: Report, classic, strict, args):
    def table_for(rows):
        return [[int(r["iteration"]), fmt_pct(r["precision_at_k"]), fmt_pct(r["recall_at_k"]),
                 f"{r['map_at_k']:.4f}", f"{r['ndcg_at_k']:.4f}"] for r in rows]

    hdr = ["Itération", "Precision@K", "Recall@K", "MAP@K", "nDCG@K"]
    if not classic:
        R.note("Résultats à insérer — non mesurés dans ce document",
               "Les résultats expérimentaux doivent provenir d'une exécution réelle sur GHIM-10K : aucune valeur n'est\n"
               "inventée ici. Après indexation des 10 000 images, exécuter :\n"
               "`python scripts/evaluate.py --queries 500 --scope 25 --iterations 5 --output results/eval_classic.csv`\n"
               "`python scripts/evaluate.py --queries 500 --scope 25 --iterations 5 --exclude-judged --output results/eval_strict.csv`\n"
               "puis régénérer ce rapport avec `--results results/eval_classic_summary.csv --strict results/eval_strict_summary.csv` :\n"
               "les tableaux, courbes et la synthèse chiffrée seront alors insérés automatiquement.")
        return
    n_q = int(classic[0]["n_queries"])
    R.p(f"Les mesures ci-dessous ont été obtenues sur **{n_q} requêtes** tirées aléatoirement (graine fixée), "
        f"avec K = {args.scope} résultats par itération. Chaque valeur est la moyenne sur l'ensemble des requêtes.")
    R.table(hdr, table_for(classic), widths=[2.4, 3.2, 3.2, 3, 3], align_right_from=1,
            caption="Protocole classique (les images déjà jugées peuvent réapparaître)")
    fig = plot_summary(classic, R.tmp / "m_classic.png", "Évolution des métriques — protocole classique")
    R.figure(fig, "Évolution des métriques en fonction de l'itération de retour de pertinence (protocole classique).")
    if strict:
        R.table(hdr, table_for(strict), widths=[2.4, 3.2, 3.2, 3, 3], align_right_from=1,
                caption="Protocole strict (images déjà jugées exclues du classement)")
        fig = plot_summary(strict, R.tmp / "m_strict.png", "Évolution des métriques — protocole strict")
        R.figure(fig, "Évolution des métriques (protocole strict : seules les images nouvelles sont comptées).")
    p0, pn = classic[0]["precision_at_k"], classic[-1]["precision_at_k"]
    txt = (f"**Lecture des résultats.** En protocole classique, la Precision@{args.scope} passe de {fmt_pct(p0)} (recherche simple) "
           f"à {fmt_pct(pn)} à l'itération {int(classic[-1]['iteration'])} (écart : {(pn - p0) * 100:+.2f} points).")
    if strict:
        s0, sn = strict[0]["precision_at_k"], strict[-1]["precision_at_k"]
        txt += (f" En protocole strict, elle passe de {fmt_pct(s0)} à {fmt_pct(sn)} ({(sn - s0) * 100:+.2f} points) : "
                "c'est cette seconde évolution qui mesure l'apport réel du réajustement des poids, "
                "puisque le protocole classique réintroduit en tête les images déjà validées par l'utilisateur.")
    R.p(txt)
    R.p("Ces chiffres reposent sur un utilisateur simulé idéal (il connaît parfaitement les catégories) ; ils constituent "
        "une borne favorable et ne remplacent pas une évaluation par des utilisateurs réels.")


def build(R: Report, a, classic, strict):
    d = R.doc
    # ------------------------------------------------------------------ couverture
    for _ in range(3):
        d.add_paragraph()
    para = d.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = para.add_run("RAPPORT DE PROJET"); r.font.size = Pt(13); r.bold = True; r.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
    para = d.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_before = Pt(18)
    r = para.add_run("VisualSearch"); r.font.size = Pt(38); r.bold = True; r.font.color.rgb = ACCENT
    para = d.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = para.add_run("Application web de gestion d'une galerie de photos\net recherche d'images par le contenu (CBIR)\navec retour de pertinence Re-weighting Type-1")
    r.font.size = Pt(15)
    for _ in range(4):
        d.add_paragraph()
    for label, val in (("Groupe", a.group), ("Membres", a.authors), ("Encadrant(e)", a.supervisor),
                       ("Établissement", a.institution), ("Année universitaire", a.year)):
        para = d.add_paragraph(); para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_after = Pt(3)
        rr = para.add_run(f"{label} : "); rr.bold = True
        para.add_run(val)
    R.page_break()

    R.toc()
    R.page_break()

    # ------------------------------------------------------------------ 1. Introduction
    R.h(1, "1. Introduction")
    R.h(2, "1.1 Contexte et problématique")
    R.p("Les collections d'images numériques ont atteint des volumes qui rendent leur exploitation manuelle impossible. "
        "Retrouver une image par son nom de fichier ou par des mots-clés suppose une annotation préalable, coûteuse et subjective. "
        "La recherche d'images par le contenu (*Content-Based Image Retrieval*, CBIR) propose une alternative : l'utilisateur fournit "
        "une image exemple et le système retourne les images visuellement proches, en comparant des descripteurs calculés "
        "directement sur les pixels.")
    R.p("Les descripteurs de bas niveau (couleur, texture) ne capturent toutefois pas toujours l'intention sémantique de l'utilisateur : "
        "c'est le « fossé sémantique ». Le **retour de pertinence** (*relevance feedback*) atténue ce problème en faisant participer "
        "l'utilisateur : il désigne, parmi les résultats, ceux qui sont pertinents, et le système réajuste sa mesure de similarité.")
    R.h(2, "1.2 Cahier des charges")
    R.p("Le sujet demande une application web de gestion d'une galerie de photos, accessible après authentification, organisée en deux tâches.")
    R.table(["Tâche", "Exigence", "Réalisation"],
            [["1", "Charger / télécharger / supprimer une image ou un ensemble d'images", "Import multiple, téléchargement individuel ou ZIP, suppression multiple (§4.4)"],
             ["1", "Organiser en hiérarchie de catégories", "Catégories imbriquées sans limite de profondeur, déplacement avec détection de cycles (§3.3)"],
             ["1", "Créer de nouvelles images par transformation (crop, échelle…)", "12 transformations ; l'original est conservé, filiation enregistrée (§4.5)"],
             ["1", "Consommer une API REST Flask / Flask-RESTful", "API indépendante, 5 endpoints, authentifiable par clé (§3.4)"],
             ["1", "Descripteurs couleur : histogramme, moments, couleurs dominantes", "HSV 8×3×3, 9 moments, K-Means (§2.2)"],
             ["1", "Descripteurs texture : GLCM, histogramme LBP", "6 caractéristiques de Haralick, LBP uniforme (§2.3)"],
             ["1", "Afficher les descripteurs d'une image", "Page de détail : histogrammes interactifs, palette, tableaux (§4.6)"],
             ["2", "Recherche simple", "Distance euclidienne pondérée (§2.4)"],
             ["2", "Recherche avec retour de pertinence — technique du groupe", "**Re-weighting Type-1** (groupe G6), §2.5 et §4.3"]],
            widths=[1.2, 7.2, 8], caption="Correspondance entre le cahier des charges et la réalisation")
    R.h(2, "1.3 Organisation du rapport")
    R.p("Le chapitre 2 présente les fondements théoriques (descripteurs, similarité, retour de pertinence). Le chapitre 3 décrit "
        "l'architecture et la conception. Le chapitre 4 détaille l'implémentation. Le chapitre 5 traite de la qualité logicielle et "
        "de la sécurité. Le chapitre 6 présente le protocole et les résultats d'évaluation. Le chapitre 7 conclut.")

    # ------------------------------------------------------------------ 2. Étude théorique
    R.h(1, "2. Étude théorique")
    R.h(2, "2.1 Principe d'un système CBIR")
    R.p("Un système CBIR se décompose en deux phases. **Hors ligne**, chaque image de la base est transformée en un vecteur de "
        "caractéristiques (*indexation*). **En ligne**, l'image requête subit la même transformation puis ses caractéristiques sont "
        "comparées à celles de la base au moyen d'une mesure de distance ; les images sont triées par distance croissante.")
    R.p("Le vecteur global de VisualSearch est la concaténation de quatre blocs :")
    R.table(["Bloc", "Dimensions", "Information capturée"],
            [["Histogramme de couleur HSV", "72", "Distribution globale des couleurs"],
             ["Moments de couleur HSV", "9", "Moyenne, dispersion, asymétrie de chaque canal"],
             ["GLCM (Haralick)", "6", "Organisation spatiale des niveaux de gris"],
             ["LBP uniforme", "10", "Micro-motifs locaux de texture"],
             ["**Total**", "**97**", "Les couleurs dominantes sont affichées mais exclues du vecteur"]],
            widths=[6, 2.4, 8], caption="Structure du vecteur de caractéristiques")

    R.h(2, "2.2 Descripteurs de couleur")
    R.p("Les images sont converties en RGB puis réduites (plus grand côté ≤ 256 px) pour borner le coût de calcul. "
        "L'espace **HSV** (teinte, saturation, valeur) est utilisé car il sépare la chromaticité de la luminosité et se rapproche "
        "mieux de la perception humaine que l'espace RGB.")
    R.p("**Histogramme de couleur.** L'espace HSV est quantifié en 8 intervalles de teinte, 3 de saturation et 3 de valeur ; "
        "l'histogramme joint est normalisé (somme = 1), ce qui le rend indépendant de la résolution.")
    R.eq("hist")
    R.p("**Moments de couleur.** Pour chaque canal c ∈ {H, S, V}, on calcule la moyenne μ, l'écart-type σ et l'asymétrie standardisée s "
        "(*skewness*), soit 9 valeurs. Lorsque σ est quasi nul, s est fixée à 0 pour éviter une division par zéro.")
    R.eq("mean")
    R.p("**Couleurs dominantes.** Un K-Means (k ≤ 5) est appliqué à un échantillon de 2 000 pixels RGB (graine fixée pour la reproductibilité). "
        "Les centres, leur code hexadécimal et leur proportion sont affichés. Ils ne sont pas concaténés au vecteur de recherche : "
        "les centres K-Means n'ont pas d'ordre stable d'une image à l'autre et leur comparaison composante par composante n'aurait pas de sens.")

    R.h(2, "2.3 Descripteurs de texture")
    R.p("**Matrice de co-occurrence des niveaux de gris (GLCM).** L'image est convertie en niveaux de gris puis quantifiée sur 32 niveaux. "
        "La matrice p(i, j) donne la fréquence des paires de pixels (i, j) séparés d'une distance 1 selon l'orientation considérée. "
        "Elle est calculée pour 0°, 45°, 90° et 135° (matrice symétrique, normalisée), et les caractéristiques sont moyennées sur les orientations.")
    R.eq("glcm", number=False)
    R.eq("glcm2")
    R.p("**Motifs binaires locaux (LBP).** Chaque pixel est comparé à ses P = 8 voisins situés sur un cercle de rayon R = 1 ; le résultat "
        "est un code binaire. La variante *uniform* ne distingue que les motifs ayant au plus deux transitions 0/1, ce qui donne P + 2 = 10 "
        "classes. L'histogramme normalisé de ces classes décrit la texture.")
    R.eq("lbp")

    R.h(2, "2.4 Normalisation et mesure de similarité")
    R.p("Les caractéristiques ont des échelles très différentes (un bin d'histogramme est inférieur à 1, un contraste GLCM peut dépasser 100). "
        "Sans correction, les grandes valeurs dominent la distance. Chaque composante j est donc centrée-réduite sur l'ensemble des images indexées de l'utilisateur :")
    R.eq("zscore")
    R.p("Les blocs ayant des tailles très différentes (72 contre 6), un histogramme de 72 composantes écraserait les 6 caractéristiques GLCM. "
        "Un **poids de base** b_i = 1/n_g (n_g = taille du bloc de la composante i) équilibre l'influence des blocs. Il s'agit d'un a priori fixe, "
        "distinct des poids w_i appris par le retour de pertinence. La distance utilisée est la distance euclidienne pondérée :")
    R.eq("dist")

    R.h(2, "2.5 Retour de pertinence et Re-weighting Type-1")
    R.p("Le retour de pertinence est un processus interactif : le système présente des résultats, l'utilisateur en désigne certains comme "
        "pertinents, le système en déduit une nouvelle représentation de la requête et/ou une nouvelle mesure de similarité, puis relance la recherche. "
        "Les méthodes se répartissent en trois grandes familles, correspondant aux techniques attribuées aux groupes du projet :")
    R.bullets(["**Query Vector Modification** : on déplace le point requête vers les images pertinentes (et loin des non pertinentes) ;",
               "**Feature Relevance Estimation** : on estime l'importance de chaque caractéristique ;",
               "**Re-weighting** : on réajuste les poids de la distance à partir de la dispersion des caractéristiques — *technique du groupe G6, Type-1*."])
    R.p("Le principe du Re-weighting est le suivant : si une caractéristique varie peu parmi les images jugées pertinentes, elle est probablement "
        "discriminante pour le concept recherché et doit recevoir un poids élevé ; si elle varie autant parmi les pertinents que parmi les résultats "
        "retournés, elle n'apporte rien. La technique Type-1 formalise cette intuition par un rapport d'écarts-types :")
    R.eq("type1")
    R.p("où σ_rel,i est l'écart-type de la composante i sur l'ensemble R des images pertinentes (augmenté de l'image requête), σ_Nr,i son écart-type "
        "sur les N_r images retournées à l'itération précédente, et ε une petite constante qui évite les divisions par zéro. La requête est "
        "remplacée par la moyenne des vecteurs pertinents :")
    R.eq("query")
    R.p("Type-1 n'exploite que les images pertinentes : les images non pertinentes sont ignorées.")
    R.figure(R.diagrams["loop"], "Déroulement d'une session de recherche avec retour de pertinence.", 16)
    R.note("Précision sur les sources",
           "La formulation ci-dessus correspond à l'implémentation du dépôt, qui se réfère au papier de Renuka Devi (IJARCCE, 2016) cité en référence [1]. "
           "Avant la soutenance, il est recommandé de vérifier la correspondance exacte des équations (numérotation, définition de N_r) avec la version du papier fournie en cours.",
           fill="E0F2FE")
    R.h(3, "Garde-fous d'implémentation")
    R.p("Ces choix ne figurent pas dans la formule théorique ; ils servent à stabiliser le calcul avec peu d'exemples et doivent être "
        "présentés comme des décisions d'implémentation :")
    R.numbered(["**Au moins une image pertinente en plus de la requête.** Avec un seul exemple, σ_rel est nul partout et les poids deviendraient proportionnels à σ_Nr, ce qui n'a aucun sens.",
                "**Bornage et normalisation des poids.** Avec 2 ou 3 exemples, une composante identique par hasard donnerait un poids voisin de 1/ε = 10 000. Les poids sont donc limités autour de leur médiane (rapport ρ = 20) puis ramenés à une somme de 97 :",
                "**Cumul des pertinents.** Les images désignées aux itérations précédentes restent prises en compte.",
                "**Requête exclue du classement** : elle sert à apprendre mais ne revient pas dans les résultats."])
    R.eq("clip")

    # ------------------------------------------------------------------ 3. Conception
    R.h(1, "3. Architecture et conception")
    R.h(2, "3.1 Vue d'ensemble")
    R.p("L'application sépare trois responsabilités : l'**application web** (interface, gestion des fichiers, recherche), l'**API REST** "
        "(calcul des descripteurs) et le **stockage** (SQLite pour les métadonnées et vecteurs, disque pour les images).")
    R.figure(R.diagrams["architecture"], "Architecture logique de VisualSearch.", 14)
    R.p("Isoler le calcul des descripteurs dans une API répond à l'énoncé (consommation d'un service REST) et apporte des avantages concrets : "
        "le service se teste seul, peut être consommé par d'autres clients, ne duplique pas le code d'extraction côté web, et peut être déployé et mis à l'échelle séparément. "
        "Si l'API est indisponible lors d'un import, les images sont conservées sans descripteurs ; l'action « Calculer les descripteurs manquants » rattrape ensuite le retard.")
    R.h(2, "3.2 Choix technologiques")
    R.table(["Domaine", "Technologie", "Justification"],
            [["Web", "Flask 3 (application factory + blueprints)", "Léger, testable, imposé par l'énoncé"],
             ["API", "Flask-RESTful", "Imposé ; ressources et codes HTTP explicites"],
             ["Image", "Pillow", "Lecture, conversions, transformations, vignettes"],
             ["Calcul", "NumPy", "Vectorisation : distance sur 10 000 × 97 en quelques ms"],
             ["Vision", "scikit-image", "Implémentations de référence de GLCM et LBP"],
             ["Apprentissage", "scikit-learn", "K-Means des couleurs dominantes"],
             ["Données", "SQLite (mode WAL)", "Sans serveur, transactionnel, adapté à ce volume"],
             ["Interface", "HTML/CSS/JS natifs, Chart.js", "Aucune étape de build ; Chart.js et polices embarqués (hors-ligne)"],
             ["Qualité", "pytest, ruff, GitHub Actions", "Tests, analyse statique, intégration continue"],
             ["Déploiement", "Docker, Gunicorn/Waitress", "Exécution reproductible"]],
            widths=[2.7, 5.5, 8.2], caption="Technologies employées")
    R.h(2, "3.3 Modèle de données et hiérarchie de catégories")
    R.figure(R.diagrams["er"], "Modèle relationnel de l'application.", 13.5)
    R.p("La hiérarchie de catégories est stockée par **liste d'adjacence** (colonne `parent_id`). Ce modèle est simple et permet l'ajout, "
        "le renommage et le déplacement d'un nœud par une seule mise à jour. Les parcours (descendants d'une catégorie, fil d'Ariane) "
        "utilisent des **requêtes récursives (CTE)** : sélectionner une catégorie affiche donc aussi les images de ses sous-catégories. "
        "La suppression d'une catégorie supprime ses sous-catégories (`ON DELETE CASCADE`) mais conserve les images, qui deviennent « sans catégorie » "
        "(`ON DELETE SET NULL`). Le déplacement d'une catégorie vérifie qu'elle n'est pas rattachée à l'une de ses propres descendantes, ce qui créerait un cycle.")
    R.p("Les vecteurs de caractéristiques sont enregistrés en `float32` (BLOB de 388 octets), les détails d'affichage en JSON. Les fichiers images "
        "ne sont pas stockés dans la base : un schéma versionné (`PRAGMA user_version`) applique des migrations purement additives, de sorte qu'une base "
        "indexée avec une version antérieure reste utilisable sans recalcul.")
    R.h(2, "3.4 API REST de descripteurs")
    R.table(["Méthode", "Endpoint", "Rôle"],
            [["GET", "`/api/health`", "État du service, version, dimension du vecteur"],
             ["GET", "`/api/descriptors/info`", "Description des descripteurs : paramètres, structure du vecteur, limites"],
             ["POST", "`/api/descriptors`", "Couleur + texture + vecteur global (une ou plusieurs images)"],
             ["POST", "`/api/descriptors/color`", "Histogramme, moments, couleurs dominantes"],
             ["POST", "`/api/descriptors/texture`", "GLCM + histogramme LBP"]],
            widths=[2, 5.6, 8.8], caption="Endpoints de l'API")
    R.p("Les requêtes POST sont de type `multipart/form-data` avec un champ `images` répétable, ce qui permet de traiter un **ensemble** d'images en un appel. "
        "Une image illisible ne fait pas échouer le lot : l'entrée concernée contient un champ `error`. L'API peut être protégée par une clé "
        "(en-tête `X-API-Key`, comparée en temps constant), limite le nombre d'images par requête et refuse les images de dimensions excessives.")
    R.code("""curl -X POST -H "X-API-Key: $KEY" \\
     -F "images=@image1.jpg" -F "images=@image2.png" \\
     http://127.0.0.1:5001/api/descriptors""")

    # ------------------------------------------------------------------ 4. Implémentation
    R.h(1, "4. Implémentation")
    R.h(2, "4.1 Organisation du code")
    R.code("""VisualSearch-CBIR/
├── api/            API REST : app.py (factory), descriptors.py (calculs purs)
├── webapp/
│   ├── __init__.py     fabrique d'application (create_app)
│   ├── config.py       profils development / production / testing
│   ├── db.py           schéma, migrations, requêtes hiérarchiques
│   ├── security.py     CSRF, en-têtes, limiteur de connexions
│   ├── blueprints/     auth · gallery · images · search
│   ├── services/       api_client · imagestore · transforms · retrieval
│   ├── templates/ static/
├── scripts/        index_dataset.py · evaluate.py · make_figures.py
├── tests/          suite pytest
├── docs/           génération du rapport
├── Dockerfile · docker-compose.yml · Makefile · .github/workflows/ci.yml
└── wsgi.py · run_all.py""")
    R.h(2, "4.2 Moteur de recherche")
    R.p("Le moteur charge en mémoire, pour l'utilisateur courant, la matrice des vecteurs (10 000 × 97 en `float64`, soit environ 8 Mo), la normalise "
        "(z-score) et la met en cache. Le cache est invalidé lorsque le nombre, l'identifiant maximal ou la somme des identifiants de descripteurs change. "
        "Une recherche est une opération matricielle unique ; la sélection des K meilleurs résultats utilise `argpartition` (O(n)) puis un tri des K éléments. "
        "Pour ce volume, une recherche exhaustive est plus simple et plus fiable qu'un index approximatif.")
    R.h(2, "4.3 Retour de pertinence")
    R.p("Le serveur est **sans état** : à chaque itération, le navigateur renvoie l'image requête, les images pertinentes cumulées et les images affichées (N_r). "
        "Le moteur recalcule alors la requête et les poids. Cette conception évite toute session côté serveur et rend chaque appel indépendant et testable.")
    R.code("""def feedback_type1(self, query_id, relevant_ids, retrieved_ids, k, max_ratio=20.0):
    rel = [query_id] + [i for i in unique(relevant_ids) if i != query_id]
    if len(rel) < 2:  return None                     # garde-fou n°1
    Zr, Zn = Z[rel], Z[retrieved_ids]                 # pertinents / retournés (Nr)
    q_new = Zr.mean(axis=0)                           # nouvelle requête
    w = (EPS + Zn.std(axis=0)) / (EPS + Zr.std(axis=0))   # formule Type-1
    w = clip(w, median(w)/max_ratio, median(w)*max_ratio) # garde-fou n°2
    w *= DIM / w.sum()
    return rank(q_new, w, k)""")
    R.p("L'interface affiche, pour chaque bloc de descripteurs, le poids moyen relatif à la moyenne globale (1 = neutre) : un utilisateur voit ainsi si le système "
        "a jugé la couleur ou la texture plus discriminante pour sa requête.")
    R.h(2, "4.4 Gestion des fichiers")
    R.bullets(["**Import** multiple ; le type est contrôlé par l'extension *et* par le décodage réel de l'image (Pillow) ; l'extension stockée est dérivée du format détecté, jamais du nom fourni ;",
               "**Vignettes** JPEG 256 px générées à l'import (galerie rapide) ;",
               "**Téléchargement** d'une image ou d'un ensemble (archive ZIP, noms dédoublonnés) ;",
               "**Suppression** multiple : fichiers, vignettes et descripteurs sont supprimés ;",
               "**Isolation** : chaque utilisateur a son dossier ; toute image d'autrui répond 404."])
    R.h(2, "4.5 Transformations")
    R.table(["Transformation", "Paramètres", "Contrôles"],
            [["Recadrer (crop)", "x, y, largeur, hauteur", "Zone incluse dans l'image"],
             ["Changer l'échelle", "pourcentage ou largeur/hauteur", "1 à 10 000 px, 40 Mpx maximum"],
             ["Rotation", "angle", "−3600° à 3600° ; canevas agrandi"],
             ["Miroirs H/V, niveaux de gris, négatif, accentuation", "—", "—"],
             ["Flou gaussien", "rayon", "0 à 50"],
             ["Luminosité, contraste, saturation", "facteur", "0 à 10 ; NaN/∞ refusés"]],
            widths=[6, 5, 5.4], caption="Transformations disponibles")
    R.p("Chaque transformation produit un **nouveau fichier** ; l'original n'est jamais modifié. La relation parent → enfant est enregistrée "
        "(`parent_image_id`) et affichée sur la page de détail. L'orientation EXIF est respectée, ce qui évite les photos de téléphone « couchées ». "
        "Les descripteurs de la nouvelle image sont calculés par l'API.")
    R.h(2, "4.6 Interface utilisateur")
    R.bullets(["**Vue d'ensemble** : volumes, taux d'indexation, catégories, espace occupé, ajouts récents, état de l'API ;",
               "**Galerie** : arbre de catégories, filtre par nom, pagination, sélection multiple, actions par lot ;",
               "**Détail d'une image** : informations, transformations, histogramme HSV et LBP (Chart.js), palette de couleurs dominantes, moments, propriétés GLCM ;",
               "**Recherche** : image requête, recherche simple, sélection des images pertinentes (bordure verte), boucle de retour de pertinence, barres de poids relatifs."])
    R.h(2, "4.7 Indexation de GHIM-10K")
    R.p("Le script `scripts/index_dataset.py` importe un dossier d'images, calcule les descripteurs en parallèle (appel direct du module de calcul, valeurs identiques à celles de l'API), "
        "crée les catégories à partir des sous-dossiers — ou, pour un dossier plat, par blocs de N images triées numériquement — puis enregistre vignettes, métadonnées et vecteurs. "
        "Il est relançable (les images déjà importées sont ignorées) et couvert par des tests automatisés.")
    R.note("Vigilance sur la vérité terrain",
           "Le découpage d'un dossier plat en classes de 500 images suppose que l'ordre numérique des fichiers regroupe effectivement les classes du jeu de données. "
           "Il faut le vérifier sur l'archive téléchargée avant de s'en servir comme vérité terrain d'évaluation : des catégories erronées fausseraient toutes les métriques.")

    # ------------------------------------------------------------------ 5. Qualité & sécurité
    R.h(1, "5. Qualité logicielle et sécurité")
    R.h(2, "5.1 Tests et intégration continue")
    R.p(f"La suite comprend **{N_TESTS} tests automatisés** pour une **couverture de {COVERAGE} %** du code (API, application web, scripts). "
        "Elle s'exécute en une quinzaine de secondes et est rejouée à chaque *push* par GitHub Actions (Python 3.10 et 3.12), avec l'analyse statique `ruff`.")
    R.table(["Domaine testé", "Exemples de vérifications"],
            [["Descripteurs", "dimension 97 ; histogrammes normalisés ; image uniforme (contraste 0, homogénéité 1) ; rouge pur → teinte ≈ 0 et couleur dominante #ff0000 ; déterminisme ; modes RGBA/L/P/CMYK ; image corrompue"],
             ["API REST", "lot d'images ; une image invalide n'interrompt pas le lot ; clé d'API ; limite du nombre de fichiers ; erreurs JSON"],
             ["Moteur Type-1", "formule des poids recalculée indépendamment ; requête = moyenne ; poids bornés et normalisés ; cas sans pertinent ; amélioration sur données synthétiques ; cache"],
             ["Application web", "inscription/connexion ; import valide et invalide ; ZIP ; suppression en cascade ; catégories hiérarchiques ; 13 transformations ; recherche et feedback de bout en bout"],
             ["Sécurité", "CSRF ; en-têtes ; XSS via nom de fichier ; traversée de chemin ; isolation entre utilisateurs ; limiteur de connexions ; redirections ouvertes ; bombe de décompression"],
             ["Évaluation", "métriques sur valeurs calculées à la main ; protocoles classique et strict ; reproductibilité"]],
            widths=[3.2, 13.2], caption="Périmètre de la suite de tests")
    R.h(2, "5.2 Sécurité")
    R.table(["Menace", "Mesure"],
            [["Usurpation de requête (CSRF)", "Jeton de session comparé en temps constant sur tout POST, y compris les appels JSON (en-tête)"],
             ["Injection de script (XSS)", "Échappement Jinja2 ; échappement explicite côté JavaScript ; CSP `script-src 'self'` sans script inline"],
             ["Injection SQL", "Requêtes paramétrées ; `LIKE` échappé (recherche littérale)"],
             ["Force brute", "Limiteur par couple IP + identifiant (5 échecs / 5 min) ; vérification d'un hash factice pour les comptes inconnus (pas d'énumération temporelle)"],
             ["Mots de passe", "Hash salé (Werkzeug), 8 caractères minimum ; jamais journalisés"],
             ["Session", "Cookie HttpOnly, SameSite=Lax, Secure en production ; session régénérée à la connexion ; durée limitée à 8 h"],
             ["Fichiers hostiles", "Décodage réel, format autorisé, nombre de pixels borné, nom de stockage généré (UUID), extension dérivée du format"],
             ["Accès à autrui", "Toute requête filtrée par user_id ; 404 plutôt que 403 (l'existence n'est pas révélée)"],
             ["Redirections ouvertes", "Seuls les chemins locaux sont acceptés après connexion et pour le retour de page"],
             ["Configuration", "SECRET_KEY obligatoire (≥ 32 car.) en production ; HSTS ; en-têtes anti-clickjacking et nosniff"],
             ["Dépendances externes", "Chart.js et polices embarqués : aucune requête vers un CDN tiers"]],
            widths=[4, 12.4], caption="Mesures de sécurité implémentées")
    R.h(2, "5.3 Déploiement")
    R.p("Un `Dockerfile` (utilisateur non privilégié) et un `docker-compose.yml` lancent l'API et l'application web derrière Gunicorn, avec sondes de santé, "
        "volume persistant pour la base et les images, et API non exposée à l'extérieur du réseau interne. Le démarrage échoue explicitement si les secrets ne sont pas définis.")
    R.p("**Limites assumées :** le limiteur de connexions est en mémoire du processus (avec plusieurs *workers*, un stockage partagé de type Redis serait nécessaire) ; "
        "SQLite est adapté à un usage mono-site mais pas à une forte charge d'écriture concurrente ; l'import web reste synchrone (le script d'indexation est préférable pour de gros volumes).")

    # ------------------------------------------------------------------ 6. Évaluation
    R.h(1, "6. Évaluation expérimentale")
    R.h(2, "6.1 Protocole")
    R.p("**Jeu de données.** GHIM-10K : 10 000 images de scènes naturelles réparties en classes de 500 images (vérifier sur l'archive téléchargée). "
        "La catégorie d'une image sert de vérité terrain : deux images sont pertinentes si elles appartiennent à la même catégorie.")
    R.p("**Utilisateur simulé.** À chaque itération, il marque comme pertinentes les images retournées de la catégorie de la requête. "
        "Les requêtes sont tirées au hasard (graine fixée) parmi les images appartenant à une catégorie d'au moins deux images.")
    R.p("**Deux protocoles de comptage.** Dans le protocole *classique*, les images déjà jugées peuvent réapparaître dans les K résultats : c'est le "
        "comportement d'une interface réelle, mais il gonfle les métriques puisque ces images sont par construction pertinentes. Dans le protocole *strict*, "
        "les images déjà jugées sont retirées du classement : seules les images nouvelles sont comptées, ce qui mesure l'apport réel du réajustement.")
    R.p("**Métriques** (calculées sur les K premiers résultats, requête exclue) :")
    R.eq("prec")
    R.eq("ap")
    R.h(2, "6.2 Résultats")
    results_section(R, classic, strict, a)
    R.h(2, "6.3 Limites de l'évaluation")
    R.bullets(["Les catégories sont un **proxy** de la pertinence : deux images de catégories différentes peuvent être visuellement proches, et inversement.",
               "L'utilisateur simulé est **idéal** : il ne se trompe jamais et juge tous les résultats affichés.",
               "Le Recall@K est borné par K / |catégorie| (par exemple 25/500 = 5 %) : il doit se lire comme un indicateur relatif, non absolu.",
               "Une moyenne peut masquer des requêtes dont le résultat se dégrade après feedback ; l'analyse par requête est possible grâce au CSV détaillé."])

    # ------------------------------------------------------------------ 7. Conclusion
    R.h(1, "7. Conclusion et perspectives")
    R.p("Le projet livre une application web complète répondant aux deux tâches : gestion d'une galerie (import, téléchargement, suppression, hiérarchie de catégories, "
        "transformations), consommation d'une API REST Flask-RESTful calculant des descripteurs de couleur et de texture, affichage de ces descripteurs, "
        "et recherche d'images par le contenu avec retour de pertinence Re-weighting Type-1. Un soin particulier a été apporté à la reproductibilité de l'évaluation, "
        "à la sécurité et à la qualité logicielle.")
    R.p("**Perspectives :** ajouter des descripteurs de forme (HOG) ; traiter la teinte comme une variable circulaire dans les moments ; comparer à une base de référence "
        "par plongements CNN ; mener une évaluation avec de vrais utilisateurs ; introduire un index approximatif (FAISS) et une file de tâches pour l'indexation asynchrone "
        "si la collection grandit fortement.")

    R.h(1, "Références")
    for i, ref in enumerate([
        "Renuka Devi S. M., *Reweighing Strategies for Relevance Feedback in CBIR*, International Journal of Advanced Research in Computer and Communication Engineering (IJARCCE), vol. 5, n° 11, 2016.",
        "Haralick R. M., Shanmugam K., Dinstein I., *Textural Features for Image Classification*, IEEE Trans. Systems, Man, and Cybernetics, 1973.",
        "Ojala T., Pietikäinen M., Mäenpää T., *Multiresolution Gray-Scale and Rotation Invariant Texture Classification with Local Binary Patterns*, IEEE TPAMI, 2002.",
        "Rui Y., Huang T. S., Mehrotra S., *Content-Based Image Retrieval with Relevance Feedback in MARS*, IEEE ICIP, 1997.",
        "Documentation officielle : Flask, Flask-RESTful, NumPy, scikit-image, scikit-learn, Pillow."], 1):
        para = d.add_paragraph(); para.paragraph_format.left_indent = Cm(0.8); para.paragraph_format.first_line_indent = Cm(-0.8)
        R.runs(para, f"[{i}]  {ref}", size=9.5)

    # ------------------------------------------------------------------ Annexes
    R.h(1, "Annexe A — Installation et lancement")
    R.code("""# Environnement
python -m venv .venv && source .venv/bin/activate        # Windows : .\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt

# Lancement (développement) : API sur :5001 et application sur :5000
python run_all.py

# Indexation de GHIM-10K (relançable) puis évaluation
python scripts/index_dataset.py --folder data/ghim-10k --username admin --workers 2
python scripts/evaluate.py --queries 500 --scope 25 --iterations 5 --output results/eval_classic.csv
python scripts/evaluate.py --queries 500 --scope 25 --iterations 5 --exclude-judged --output results/eval_strict.csv

# Tests
pip install -r requirements-dev.txt && pytest

# Production (Docker)
SECRET_KEY=... DESCRIPTOR_API_KEY=... docker compose up --build""")
    R.h(1, "Annexe B — Captures d'écran")
    shots = [("dashboard.png", "Vue d'ensemble"), ("gallery.png", "Galerie et arbre de catégories"),
             ("detail.png", "Descripteurs d'une image"), ("search.png", "Recherche simple"),
             ("feedback.png", "Retour de pertinence et poids appris")]
    found = [(a.screens / f, t) for f, t in shots if a.screens and (a.screens / f).exists()]
    if found:
        for path, title in found:
            R.figure(path, title, 15)
    else:
        R.note("Captures à insérer",
               "Placer les captures dans `docs/screens/` sous les noms `dashboard.png`, `gallery.png`, `detail.png`, `search.png` et `feedback.png`, "
               "puis régénérer le rapport avec l'option `--screens docs/screens`.")
    R.footer()


# =========================================================================== #
# Orchestration en deux passes
# =========================================================================== #
def make_docx(a, toc_pages, out: Path, tmp: Path, classic, strict, headings=None) -> list:
    R = Report(tmp, toc_pages)
    R.TOC_ENTRIES = headings or []
    R.diagrams = diagrams.build_all(tmp)
    build(R, a, classic, strict)
    R.doc.save(out)
    return R.headings


def to_pdf(docx: Path, outdir: Path) -> Path | None:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(docx)],
                   check=True, capture_output=True, timeout=240)
    pdf = outdir / (docx.stem + ".pdf")
    return pdf if pdf.exists() else None


def find_pages(pdf: Path, headings) -> dict[str, int]:
    from pypdf import PdfReader
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()           # noqa: E731
    pages = [norm(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]
    start, result = 2, {}                                             # pages 1-2 : couverture + sommaire
    for _lvl, title in headings:
        key = norm(title)[:45]
        for i in range(start, len(pages)):
            if key in pages[i]:
                result[title] = i + 1
                start = i
                break
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", default="G6")
    ap.add_argument("--authors", default="[Noms des membres du groupe]")
    ap.add_argument("--supervisor", default="[Nom de l'encadrant]")
    ap.add_argument("--institution", default="[Établissement / Filière]")
    ap.add_argument("--year", default="2026-2027")
    ap.add_argument("--results", type=Path, help="CSV résumé du protocole classique")
    ap.add_argument("--strict", type=Path, help="CSV résumé du protocole strict")
    ap.add_argument("--scope", type=int, default=25, help="K utilisé lors de l'évaluation (pour le texte)")
    ap.add_argument("--screens", type=Path, default=HERE / "screens")
    ap.add_argument("--output", type=Path, default=HERE / "Rapport_VisualSearch_G6.docx")
    a = ap.parse_args()

    classic = read_summary(a.results) if a.results and a.results.exists() else None
    strict = read_summary(a.strict) if a.strict and a.strict.exists() else None
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        headings = make_docx(a, {}, a.output, tmp, classic, strict)                    # passe 1
        pdf = to_pdf(a.output, tmp)
        if pdf:
            pages = find_pages(pdf, headings)
            make_docx(a, pages, a.output, tmp, classic, strict, headings)             # passe 2 (sommaire paginé)
            final = to_pdf(a.output, a.output.parent)
            print(f"PDF : {final}")
        else:
            make_docx(a, {}, a.output, tmp, classic, strict, headings)
            print("LibreOffice introuvable : sommaire sans numéros de page, pas de PDF.")
    print(f"DOCX : {a.output}")


if __name__ == "__main__":
    main()
