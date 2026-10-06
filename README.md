# 💻 Extract - Suíte de Diagnóstico de Hardware e Inventário de T.I.

**Extract** é uma solução profissional em Python projetada para equipes de T.I., analistas e consultores. O sistema realiza varreduras detalhadas de componentes de hardware em máquinas Windows e consolida os dados de múltiplos computadores em relatórios gerenciais editáveis (Excel) e executivos (PDF).

---

## 🚀 Funcionalidades

- **Varredura Modular e Local (`extrac.py`)**:
  - Coleta detalhada de Processador (CPU), Memória RAM (slots, velocidade e geração DDR), Placa-Mãe, Placa de Vídeo (GPU), Discos (NVMe/SSD/HDD) e Adaptadores de Rede (IP/MAC).
  - Logs de execução em tempo real via terminal.
- **Interface Gráfica Moderna (`gui_extract.py`)**:
  - Construída com `ttkbootstrap` (tema Flatly/Dark).
  - Organização de relatórios agrupados por cliente.
  - Seleção granular dos componentes a serem auditados.
  - Terminal de logs integrado para acompanhamento passo a passo.
- **Consolidação de Dados**:
  - **Planilha Excel (`.xlsx`)**: Tabela estruturada com cabeçalhos estilizados, filtros automáticos, dimensionamento inteligente de colunas e formatação zebra para fácil auditoria.
  - **Relatório Executivo PDF (`.pdf`)**: Documento formatado em orientação paisagem (A4) pronto para apresentação a gestores e clientes.

---

## 🛠️ Requisitos e Instalação

### Pré-requisitos
- Python 3.8 ou superior instalado no Windows.

### Passos de Instalação

1. **Clone o repositório ou baixe os arquivos fonte:**
   ```cmd
   git clone https://github.com/SEU_USUARIO/Extract.git
   cd Extract
   ```

2. **Instale as dependências exigidas:**
   ```cmd
   pip install -r requirements.txt
   ```

---

## 🖥️ Como Usar

### Execução em Modo de Desenvolvimento

Para rodar a interface gráfica diretamente pelo Python:

```cmd
python gui_extract.py
```

### Fluxo de Trabalho
1. **Selecione a Pasta do Cliente**: Escolha a pasta onde os logs das máquinas serão salvos ou crie um novo cliente.
2. **Execute a Varredura**: Clique em `⚡ EXECUTAR VARREDURA NESTA MÁQUINA`. O terminal integrado exibirá o progresso da extração em tempo real.
3. **Consolide os Relatórios**: Após realizar a varredura em uma ou mais máquinas da rede (salvando os arquivos `*-info.txt` na pasta do cliente), clique em `🚀 GERAR / ATUALIZAR CONSOLIDAÇÃO DE RELATÓRIOS` para gerar o arquivo `.xlsx` e/ou `.pdf`.

---

## 📦 Compilação para Executável único (`.exe`)

Para empacotar toda a aplicação em um único executável que pode ser utilizado em qualquer máquina Windows sem necessidade de instalar o Python:

 Execute o módulo do PyInstaller através do interpretador do Python:

```cmd
python -m PyInstaller --noconsole --onefile --name "Extract" --collect-all ttkbootstrap gui_extract.py
```

O arquivo executável `Extract.exe` será gerado dentro do diretório `dist/`.

---

## 📂 Estrutura do Repositório

```text
Extract/
├── extrac.py          # Backend de varredura e coleta de hardware via PowerShell/CIM
├── gui_extract.py     # Frontend gráfico (Tkinter/ttkbootstrap) e motor de consolidação
├── requirements.txt   # Dependências do projeto
├── README.md          # Documentação do sistema
├── LICENSE            # Licença de uso
└── .gitignore         # Arquivos ignorados pelo Git (logs, builds e temporários)
```

---

## 📄 Licença

Este projeto está sob a licença [MIT](LICENSE).