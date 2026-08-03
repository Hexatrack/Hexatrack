import os
import json
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
from collections import Counter

app = Flask(__name__)
app.secret_key = "hexatrack_aventure_secrete"

# Configuration des dossiers
UPLOAD_FOLDER = os.path.join('static', 'uploads')
GPX_FOLDER = os.path.join('static', 'gpx')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# S'assure que les dossiers existent sur le serveur (Render/Heroku/Local)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GPX_FOLDER, exist_ok=True)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def connexion_google_sheet(onglet_name=None):
    # Si on est sur Render/Hébergeur (variable d'environnement)
    if "GOOGLE_CREDENTIALS" in os.environ:
        creds_dict = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # En local sur ton PC
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)

    client = gspread.authorize(creds)
    
    # Remplace "Classement_Trail" par le nom de ton document s'il est différent
    spreadsheet = client.open("Classement_Trail")
    
    if onglet_name:
        try:
            return spreadsheet.worksheet(onglet_name)
        except Exception:
            return spreadsheet.add_worksheet(title=onglet_name, rows=1000, cols=11)
    return spreadsheet.sheet1

@app.route('/')
def index():
    finishers_par_distance = {'10': [], '50': [], '100': []}
    courageux_par_distance = {'10': None, '50': None, '100': None}
    local_legend_par_distance = {'10': None, '50': None, '100': None}
    belles_photos_choisies = []
    conseils_liste = []

    try:
        # Lecture depuis l'onglet MODE_PHOTOS ou l'onglet principal
        sheet_validated = connexion_google_sheet("MODE_PHOTOS") 
        tous_les_enregistrements = sheet_validated.get_all_records()

        for f in tous_les_enregistrements:
            valide_valeur = str(f.get('valide', '')).strip().upper()
            
            # Récupération du conseil / avis
            if f.get('conseil') and str(f.get('conseil')).strip():
                conseils_liste.append({
                    'nom': f.get('nom', 'Anonyme'),
                    'distance': f.get('distance', '-'),
                    'conseil': f.get('conseil'),
                    'reponse_admin': f.get('reponse_admin', '')
                })

            if valide_valeur == 'OUI':
                dist = str(f.get('distance', '')).strip()
                if dist in finishers_par_distance:
                    finishers_par_distance[dist].append(f)
                
                if f.get('photo_url') and str(f.get('photo_url')).strip():
                    belles_photos_choisies.append(f)

        for dist in ['10', '50', '100']:
            coureurs = finishers_par_distance[dist]
            if coureurs:
                coureurs_tries = sorted(coureurs, key=lambda x: str(x.get('chrono', '')))
                finishers_par_distance[dist] = coureurs_tries
                courageux_par_distance[dist] = coureurs_tries[-1]

                noms = [c.get('nom') for c in coureurs if c.get('nom')]
                if noms:
                    nom_frequent, count = Counter(noms).most_common(1)[0]
                    local_legend_par_distance[dist] = {'nom': nom_frequent, 'count': count}

    except Exception as e:
        print(f"Erreur Google Sheet: {e}")

    return render_template(
        'index.html',
        finishers=finishers_par_distance,
        courageux=courageux_par_distance,
        local_legend=local_legend_par_distance,
        photos=belles_photos_choisies,
        conseils=conseils_liste
    )

@app.route('/telecharger/<filename>')
def telecharger_gpx(filename):
    distance_map = {
        '10K.gpx': '10 KM',
        '50K.gpx': '50 KM',
        '100K.gpx': '100 KM',
        '10k.gpx': '10 KM',
        '50k.gpx': '50 KM',
        '100k.gpx': '100 KM'
    }

    if filename in distance_map:
        try:
            sheet_dl = connexion_google_sheet("TELECHARGEMENTS")
            horodatage = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            sheet_dl.append_row([horodatage, distance_map[filename]])
        except Exception as e:
            print(f"Erreur comptage téléchargement: {e}")

        return send_from_directory(GPX_FOLDER, filename, as_attachment=True)

    return redirect(url_for('index'))

@app.route('/soumettre', methods=['POST'])
def soumettre():
    nom = request.form.get('nom')
    telephone = request.form.get('telephone')
    distance = request.form.get('distance')
    chrono = request.form.get('chrono')
    strava = request.form.get('strava', '').strip()
    conseil = request.form.get('conseil', '')
    
    # Récupération des cases d'accord / refus
    acc_strava = "NON" if request.form.get('refus_strava') else "OUI"
    acc_conseil = "NON" if request.form.get('refus_conseil') else "OUI"
    
    photo_url = ""

    if not nom or not telephone or not chrono or not strava:
        flash("❌ Veuillez remplir tous les champs obligatoires.", "error")
        return redirect(url_for('index'))

    # Traitement de l'image
    if 'photo_file' in request.files:
        file = request.files['photo_file']
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            clean_nom = "".join(c for c in nom if c.isalnum() or c in (' ', '_')).rstrip().replace(' ', '_')
            full_filename = f"{clean_nom}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], full_filename)
            
            # Sauvegarde physique du fichier sur le serveur
            file.save(filepath)
            
            # Lien enregistré dans la colonne G (photo_url)
            photo_url = f"/static/uploads/{full_filename}"

    try:
        sheet_mode = connexion_google_sheet("MODE_PHOTOS")
        
        # Ordre exact des colonnes dans ton Google Sheet :
        # A: nom | B: numéro | C: distance | D: chrono | E: strava | F: accord_photo | G: photo_url | H: conseil | I: accord_conseil | J: valide | K: reponse_admin
        sheet_mode.append_row([
            nom, 
            telephone, 
            distance, 
            chrono, 
            strava, 
            acc_strava, 
            photo_url, 
            conseil, 
            acc_conseil, 
            "NON", 
            ""
        ])
        
        flash("⏳ Merci ! Ta performance a été transmise pour validation.", "success")
    except Exception as e:
        print(f"Erreur lors de l'enregistrement Sheet: {e}")
        flash("❌ Une erreur s'est produite lors de la sauvegarde.", "error")

    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
