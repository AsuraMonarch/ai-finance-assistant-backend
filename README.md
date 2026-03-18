# AI Finance Backend

A Flask-based backend for an AI-powered personal finance assistant with secure authentication, transaction tracking, and OpenAI integration.

## Features

- 🔐 Secure user authentication with password hashing
- 💾 SQLite database for persistent data storage
- 🤖 OpenAI GPT integration for financial advice
- 📊 Transaction tracking and financial insights
- 🔒 JWT token-based sessions with expiration
- 🚀 Production-ready with Gunicorn

## Setup

### Prerequisites
- Python 3.8+
- OpenAI API key

### Installation

1. Clone the repository:
```bash
git clone <your-repo-url>
cd ai-finance-backend
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your OpenAI API key
```

5. Run the application:
```bash
python app.py
```

## Environment Variables

Create a `.env` file with:
```
OPENAI_API_KEY=your_openai_api_key_here
FLASK_ENV=production
DEBUG=False
DATABASE_URL=sqlite:///finance_assistant.db
PORT=5000
```

## API Endpoints

- `GET /` - Health check
- `POST /signup` - User registration
- `POST /login` - User authentication
- `GET /transactions` - Get user transactions
- `POST /transactions` - Add new transaction
- `GET /insights` - Get financial insights
- `POST /chat` - Chat with AI assistant
- `POST /logout` - Logout user

## Deployment

### Render Deployment

1. Connect your GitHub repository to Render
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `gunicorn app:app`
4. Add environment variables in Render dashboard
5. Deploy!

### Local Development

```bash
export FLASK_ENV=development
python app.py
```

## Security

- Passwords are hashed using bcrypt
- JWT tokens expire after 7 days
- CORS configured for cross-origin requests
- Input validation on all endpoints

## License

MIT License
