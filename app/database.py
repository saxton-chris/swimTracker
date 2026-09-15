from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("sqlite:///swim_tracker.db")
SessionLocal = sessionmaker(bind=engine)
