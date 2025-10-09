"""
Poll routes.
"""
from flask import Blueprint, render_template_string

poll_bp = Blueprint("poll", __name__)

@poll_bp.route("/")
def show_poll():
    html = """
    <html>
        <head><title>Poll</title></head>
        <body>
            <h1>Which lunch option do you prefer?</h1>
            <form>
                <input type="radio" name="option" value="pizza"> Pizza<br>
                <input type="radio" name="option" value="sushi"> Sushi<br>
                <input type="radio" name="option" value="burger"> Burger<br><br>
                <input type="submit" value="Vote">
            </form>
        </body>
    </html>
    """
    return render_template_string(html)