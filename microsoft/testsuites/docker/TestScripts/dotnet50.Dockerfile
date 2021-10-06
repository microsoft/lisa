FROM mcr.microsoft.com/dotnet/sdk:5.0
RUN dotnet new console -o app -n helloworld
WORKDIR /app
RUN dotnet run
RUN dotnet publish -c Release
WORKDIR /app/bin/Release/net5.0
ENTRYPOINT ["dotnet", "helloworld.dll"]
