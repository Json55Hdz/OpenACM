import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Search, Download, User, Star, Filter } from 'lucide-react';

const Library = () => {
  const [activeTab, setActiveTab] = useState('tools');
  const [searchTerm, setSearchTerm] = useState('');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const endpoint = activeTab === 'tools' ? 'tools' : 'skills';
        const res = await fetch(`http://localhost:4000/api/${endpoint}`);
        const data = await res.json();
        setItems(data);
      } catch (error) {
        console.error('Error fetching library:', error);
        // Fallback mock data
        setItems(activeTab === 'tools' ? [
          { id: 1, name: "Web Browser Tool", description: "Advanced web browsing and scraping capabilities with browser_agent", author: "OpenACM Team", version: "1.2.0", downloads: 1243 },
          { id: 2, name: "Image Generator", description: "Connects to multiple AI image generation APIs", author: "Community", version: "0.9.1", downloads: 856 }
        ] : [
          { id: 1, name: "Professional Writer", description: "Expert in technical writing, marketing copy, and creative content", author: "JsonProductions", version: "2.1.0", downloads: 2341 },
          { id: 2, name: "Code Architect", description: "Senior full-stack architect specialized in clean architecture", author: "OpenACM", version: "1.5.0", downloads: 1876 }
        ]);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [activeTab]);

  const handleInstall = async (id) => {
    try {
      const res = await fetch(`http://localhost:4000/api/install/${activeTab}/${id}`, {
        method: 'POST'
      });
      const data = await res.json();
      alert(`✅ ${data.message}\n\nCommand: ${data.command}`);
    } catch (err) {
      alert('Installed! (Demo mode)');
    }
  };

  const filteredItems = items.filter(item =>
    item.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    item.description.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white pt-20">
      <div className="max-w-7xl mx-auto px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center mb-12"
        >
          <h1 className="text-5xl font-bold bg-gradient-to-r from-cyan-400 to-purple-500 bg-clip-text text-transparent mb-4">
            OpenACM Library
          </h1>
          <p className="text-xl text-gray-400 max-w-2xl mx-auto">
            Discover powerful tools and expert skills to enhance your OpenACM experience
          </p>
        </motion.div>

        {/* Search and Filters */}
        <div className="flex flex-col md:flex-row gap-4 mb-10">
          <div className="flex-1 relative">
            <Search className="absolute left-4 top-3.5 text-gray-400" size={20} />
            <input
              type="text"
              placeholder="Search tools and skills..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-700 rounded-2xl pl-12 py-4 text-lg focus:outline-none focus:border-cyan-500 transition-colors"
            />
          </div>
          <button className="px-8 py-4 bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 rounded-2xl flex items-center gap-3 transition-all">
            <Filter size={20} />
            <span>Filters</span>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-10 border-b border-zinc-800 pb-1">
          <button
            onClick={() => setActiveTab('tools')}
            className={`px-10 py-3 rounded-2xl font-medium transition-all ${activeTab === 'tools'
              ? 'bg-cyan-500 text-black'
              : 'bg-zinc-900 hover:bg-zinc-800 text-gray-300'}`}
          >
            🛠️ Tools
          </button>
          <button
            onClick={() => setActiveTab('skills')}
            className={`px-10 py-3 rounded-2xl font-medium transition-all ${activeTab === 'skills'
              ? 'bg-purple-500 text-white'
              : 'bg-zinc-900 hover:bg-zinc-800 text-gray-300'}`}
          >
            ✨ Skills
          </button>
        </div>

        {/* Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredItems.map((item, index) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05 }}
              className="group bg-zinc-900 border border-zinc-800 hover:border-cyan-500/30 rounded-3xl overflow-hidden transition-all hover:-translate-y-2"
            >
              <div className="h-2 bg-gradient-to-r from-cyan-400 to-purple-500"></div>
              <div className="p-8">
                <div className="flex justify-between items-start mb-6">
                  <div>
                    <h3 className="text-2xl font-semibold mb-2">{item.name}</h3>
                    <div className="flex items-center text-sm text-gray-400">
                      <User size={16} className="mr-1" />
                      {item.author}
                    </div>
                  </div>
                  <div className="text-xs px-3 py-1 bg-zinc-800 rounded-full text-cyan-400 font-mono">
                    v{item.version}
                  </div>
                </div>

                <p className="text-gray-400 leading-relaxed mb-8 line-clamp-3">
                  {item.description}
                </p>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <Download size={16} />
                    <span>{item.downloads.toLocaleString()}</span>
                  </div>

                  <button
                    onClick={() => handleInstall(item.id)}
                    className="bg-white text-black px-8 py-3 rounded-2xl font-semibold flex items-center gap-2 hover:bg-cyan-400 hover:text-black transition-all active:scale-95"
                  >
                    <Download size={18} />
                    Install
                  </button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        {filteredItems.length === 0 && (
          <div className="text-center py-20 text-gray-400">
            No results found for "{searchTerm}"
          </div>
        )}
      </div>
    </div>
  );
};

export default Library;
