# macro-onepager-config — דף "מדדי אג"ח" (אתר סטטי)

## מה זה עושה
דף web סטטי (`index.html`) שמציג מדדי אג"ח (ת"א-בונד, ת"א-ממשל, כל-בונד): תשואה, מח"מ, מרווח ודירוג ממוצע.
הנתונים ב-`data/bond_indices.json`, ונבנים ע"י `scripts/build_bond_indices.py` מאתר Bizportal (HTTP פשוט, ללא מפתחות).

## איך מפעילים במחשב
- לצפייה: פתחו `index.html` בדפדפן (או `python -m http.server` בתיקייה).
- לבנייה מחדש של הנתונים: `pip install requests beautifulsoup4` ואז `python scripts/build_bond_indices.py`.

## סודות
אין. (המאגר ציבורי – לא להכניס לכאן מפתחות.)

## ענן
- האתר מתארח ב-GitHub Pages: https://brodi1977.github.io/macro-onepager-config/
- `.github/workflows/bond_indices.yml` רץ ימים א'–ה' ב-15:30 UTC (אחרי סגירת המסחר), מריץ את הסקריפט ועושה commit אוטומטי ל-`data/bond_indices.json` אם השתנה.
- הרצה ידנית: GitHub → Actions → "Bond indices data" → Run workflow.
- עדכון הדף: ערכו `index.html`, commit ו-push ל-`main` – Pages מתעדכן אוטומטית.
