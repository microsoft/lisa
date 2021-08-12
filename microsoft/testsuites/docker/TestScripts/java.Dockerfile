FROM alpine
COPY Main.java ./
#install jdk
RUN apk add openjdk8
ENV JAVA_HOME /usr/lib/jvm/java-1.8-openjdk
ENV PATH $PATH:$JAVA_HOME/bin
#compile program
RUN javac Main.java
ENTRYPOINT java Main
