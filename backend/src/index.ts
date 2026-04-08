import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors());
app.use(express.json());

// Mock database
let tools = [
  {
    id: 1,
    name: "Web Browser Tool",
    description: "Advanced web browsing and scraping capabilities with browser_agent",
    author: "OpenACM Team",
    version: "1.2.0",
    downloads: 1243,
    type: "tool"
  },
  {
    id: 2,
    name: "Image Generator",
    description: "Connects to multiple AI image generation APIs",
    author: "Community",
    version: "0.9.1",
    downloads: 856,
    type: "tool"
  }
];

let skills = [
  {
    id: 1,
    name: "Professional Writer",
    description: "Expert in technical writing, marketing copy, and creative content",
    author: "JsonProductions",
    version: "2.1.0",
    downloads: 2341,
    category: "writing"
  },
  {
    id: 2,
    name: "Code Architect",
    description: "Senior full-stack architect specialized in clean architecture",
    author: "OpenACM",
    version: "1.5.0",
    downloads: 1876,
    category: "development"
  }
];

// Routes
app.get('/api/tools', (req, res) => {
  res.json(tools);
});

app.get('/api/skills', (req, res) => {
  res.json(skills);
});

app.post('/api/tools', (req, res) => {
  const newTool = { ...req.body, id: Date.now(), downloads: 0, type: 'tool' };
  tools.push(newTool);
  res.status(201).json(newTool);
});

app.post('/api/skills', (req, res) => {
  const newSkill = { ...req.body, id: Date.now(), downloads: 0 };
  skills.push(newSkill);
  res.status(201).json(newSkill);
});

app.post('/api/install/:type/:id', (req, res) => {
  const { type, id } = req.params;
  res.json({ 
    success: true, 
    message: `Installation command generated for ${type} #${id}`,
    command: `openacm install ${type} ${id}`
  });
});

console.log(`🚀 OpenACM Marketplace Backend running on http://localhost:${PORT}`);
app.listen(PORT, () => {
  console.log(`Server ready at http://localhost:${PORT}`);
});
