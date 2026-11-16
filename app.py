"""
Entry point.

    python app.py            development server on http://localhost:5000
    gunicorn app:app         production (Procfile, Dockerfile, render.yaml)

The application lives in the relocaitor package; the Flask app is relocaitor.web.app.
"""

from relocaitor.web.app import app, main, meta  # noqa: F401  (app is what gunicorn serves)

if __name__ == "__main__":
    main()
