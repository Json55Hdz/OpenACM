# Windows File Manager

Skill especializada para gestión de archivos en Windows usando las herramientas nativas disponibles.

**Solo aplica si OpenACM corre en Windows.** Si corre en Linux/Docker/NAS (sin escritorio), las rutas son tipo `/home/...` o `/app/...` y no existen `explorer.exe`, `notepad.exe` ni `%USERPROFILE%`: usar `write_file`, `read_file`, `list_directory` y comandos POSIX (`mkdir -p`, `echo $HOME`). Comprueba el sistema con `system_info` antes de asumir rutas.

## 🎯 Propósito

Proporcionar comandos y patrones optimizados para:
- Crear, leer y modificar archivos en rutas de Windows
- Abrir el Explorador de archivos en ubicaciones específicas
- Ejecutar aplicaciones Windows con archivos
- Manejar rutas con espacios y caracteres especiales

## 🛠️ Herramientas Utilizadas

- `write_file` - Crear/sobrescribir archivos (soporta UTF-8)
- `read_file` - Leer contenido de archivos
- `list_directory` - Listar contenido de carpetas
- `search_files` - Buscar archivos por patrón
- `run_command` - Ejecutar comandos del sistema (explorer, notepad, etc.)

## 📋 Comandos Verificados

### Crear archivo en Downloads
```python
write_file(path="C:\\Users\\{username}\\Downloads\\nombre.txt", content="...")
```

### Abrir Explorador de archivos
```cmd
explorer.exe "C:\\Users\\{username}\\Downloads"
```
**Nota:** El explorador se abre sin mostrar output. Usar comillas para rutas con espacios.

### Abrir archivo con Notepad
```cmd
notepad.exe "C:\\ruta\\al\\archivo.txt"
```

### Variables de entorno útiles
```cmd
echo %USERPROFILE%    → C:\Users\{username}
echo %APPDATA%        → C:\Users\{username}\AppData\Roaming
echo %LOCALAPPDATA%   → C:\Users\{username}\AppData\Local
```

## ⚠️ Consideraciones

1. **Rutas absolutas:** Usar rutas completas C:\\... para evitar ambigüedades
2. **Comillas:** Siempre usar comillas para rutas con espacios
3. **Permisos:** Algunas carpetas requieren permisos de administrador
4. **Codificación:** `write_file` usa UTF-8 por defecto (soporta emojis y caracteres especiales)

## 💡 Patrones Comunes

### Crear archivo y abrirlo
1. `write_file` para crear el archivo
2. `notepad.exe` o `explorer.exe` para abrirlo

### Trabajar con Downloads
```
Ruta: C:\Users\{username}\Downloads
Obtener username: echo %USERNAME%
Obtener profile: echo %USERPROFILE%
```

### Crear carpetas (si no existen)
```cmd
mkdir "C:\\ruta\\nueva\\carpeta"
```

---
*Versión: 1.1*
