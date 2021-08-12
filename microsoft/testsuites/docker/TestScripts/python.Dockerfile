FROM ubuntu:18.04
RUN apt-get update && apt-get install python3 -y
COPY helloworld.py ./
ENTRYPOINT ["python3"]
CMD ["/helloworld.py"]
