# Compilación del Importer para VEGAS Pro

La extensión de integración para VEGAS Pro (`DowPImporter.dll`) está construida en C# utilizando el formato moderno de proyectos SDK de .NET (`<Project Sdk="Microsoft.NET.Sdk">`).

## Requisitos previos

- Tener instalado el **SDK de .NET** (se recomienda la versión más reciente que tengas instalada, el proyecto compila hacia `net48` automáticamente).
- VEGAS Pro instalado en su ruta por defecto (necesario para referenciar `ScriptPortal.Vegas.dll` durante la compilación).

## Instrucciones de Compilación

1. Abre tu terminal (PowerShell o CMD).
2. Navega hasta la carpeta del código fuente de la extensión:
   ```bash
   cd importer_vegas/src
   ```
3. Ejecuta el comando de construcción de dotnet en modo Release:
   ```bash
   dotnet build DowPImporter.Vegas.csproj -c Release
   ```
4. ¡Listo! Al finalizar exitosamente, la nueva DLL compilada se ubicará en la carpeta de distribución del proyecto:
   `importer_vegas/dist/DowPImporter.dll`

## Pruebas e Instalación Manual

Si estás desarrollando y quieres aplicar rápidamente tus cambios en VEGAS Pro sin usar la herramienta interna de configuración de DowP, sigue estos pasos:

1. **Cierra VEGAS Pro por completo.** (Si está abierto, el proceso `vegas160.exe` mantendrá bloqueada la DLL y dará un error de "Permiso Denegado" al intentar sobrescribirla).
2. Copia el archivo `DowPImporter.dll` recién compilado desde la carpeta `dist/`.
3. Pégalo (y sobrescribe) en la carpeta de extensiones de aplicación del usuario en Windows:
   - **Ruta destino:** `%APPDATA%\VEGAS Pro\Application Extensions\`
   *(Ej. `C:\Users\TuUsuario\AppData\Roaming\VEGAS Pro\Application Extensions\`)*
4. Abre VEGAS Pro. Si el panel de DowP no se abre automáticamente, actívalo desde el menú superior: `View -> Window -> Extensions -> DowP Importer`.
