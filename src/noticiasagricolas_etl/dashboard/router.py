"""Dashboard routes — serves HTML pages via Jinja2 templates."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("/")
def dashboard_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/basis")
def dashboard_basis(request: Request):
    return templates.TemplateResponse("basis.html", {"request": request})


@router.get("/curve")
def dashboard_curve(request: Request):
    return templates.TemplateResponse("curve.html", {"request": request})


@router.get("/rankings")
def dashboard_rankings(request: Request):
    return templates.TemplateResponse("rankings.html", {"request": request})
