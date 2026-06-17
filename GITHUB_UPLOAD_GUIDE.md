# GitHub upload guide

Recommended repository name:

```text
ai-document-processing-automation
```

Recommended GitHub description:

```text
Human-in-the-loop AI document processing automation system for invoices, receipts, purchase orders, and contracts with extraction, validation, approval, export, and audit logs.
```

Recommended topics:

```text
ai-automation
fastapi
streamlit
document-processing
invoice-automation
ocr
human-in-the-loop
workflow-automation
llm
python
```

## Upload commands

Create an empty public GitHub repository first. Do not tick README, .gitignore, or license.

Then run inside the extracted project folder:

```powershell
git init
git add .
git commit -m "Initial commit: AI document processing automation system"
git branch -M main
git remote add origin https://github.com/SAHARIARSHOWMIK/ai-document-processing-automation.git
git push -u origin main
```

## After upload

Check:

```text
README renders correctly
Screenshots appear
Actions workflow runs
No .env/app.db/uploads/exports/.venv files are uploaded
```

If GitHub Actions fails with `ModuleNotFoundError: No module named 'app'`, confirm `.github/workflows/tests.yml` contains:

```yaml
PYTHONPATH: ${{ github.workspace }}
```

If GitHub displays config files as one line on Windows, use GitHub's web editor or ensure `.gitattributes` is committed.
