FROM python:3-alpine
ENV TZ="Asia/Singapore"

# Create app directory
WORKDIR /bot

# Install app dependencies
COPY requirements.txt ./

RUN pip install -r requirements.txt

# Bundle app source
COPY . .

CMD [ "python", "./bot.py","--host","0.0.0.0"]