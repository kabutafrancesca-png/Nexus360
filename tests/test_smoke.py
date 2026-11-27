from app import create_app

def test_app_boots():
    app = create_app()
    assert app is not None
