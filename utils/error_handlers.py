from flask import jsonify

def register_error_handlers(app):
    """Регистрация обработчиков ошибок"""

    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify({'error': 'Ресурс не найден'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

    @app.errorhandler(401)
    def unauthorized_error(error):
        return jsonify({'error': 'Неавторизован'}), 401

    @app.errorhandler(403)
    def forbidden_error(error):
        return jsonify({'error': 'Доступ запрещен'}), 403