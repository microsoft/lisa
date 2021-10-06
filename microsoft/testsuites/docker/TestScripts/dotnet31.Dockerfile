FROM mcr.microsoft.com/dotnet/core/sdk:3.1
RUN dotnet new console -o app -n helloworld
WORKDIR /app
RUN dotnet run
RUN dotnet publish -c Release
WORKDIR /app/bin/Release/netcoreapp3.1
ENTRYPOINT ["dotnet", "helloworld.dll"]
